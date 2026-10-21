#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 ai_brain_vector_engine.py — 脑库→向量化引擎 (Brain Vector Engine)
================================================================================
 flow_id   : flow_vector_brain_20261014   (§14 IRON_RULE 12步骤 STEP_7)
 版本      : v22.22.0 (minor)
 职责      : 为主库 ai_brain_enhanced_knowledge (1.5M+行) 建立本地向量索引,
             并提供增量入队/消化链路, 打通 脑库→向量 管道
 设计要点  :
   1. 零token铁律 : 仅 localhost Ollama /api/embeddings (默认11434,
      env MTSCOS_OLLAMA_EMBED_URL / MTSCOS_OLLAMA_EMBED_MODEL 可覆盖), 无外部网络
   2. 分块事务    : 每 chunk(50) 行 BEGIN IMMEDIATE/COMMIT, 嵌入结果与 checkpoint
      水位同事务落库 (严格一致, 不丢不重)
   3. 断点续传    : mt_brain_vector_checkpoint 按 job_key 记 rowid 水位, 重复运行
      自动续传; NOT EXISTS 反连接跳过已向量化行 (覆盖13+写入方的增量主通道)
   4. 内容快照队列: mt_brain_vector_queue 支持内容随队 (brain_feeding K-* id 不落
      主库, drain 不依赖主库行存在); 仅带 id 的队列行 drain 时回查主库
   5. fail-closed : Ollama 不可达 → backfill 中止(checkpoint保留)/drain 保留
      PENDING 不烧 attempts; 队列行内容缺失 → attempts+1, ≥5 熔断 FAILED
   6. 范围控制    : mt_ai_brain_vector 仅主库 SSOT, 不入三库镜像
      (db_triple_sync_engine 白名单制天然豁免; 1.5M×3KB BLOB ≈ 4.6GB 镜像无收益)
   7. 复用        : BEGIN IMMEDIATE 指数退避 / Row conn / log 复用
      ai_bulk_injector_engine (同目录 import)
 向量存储  : float32 little-endian BLOB (array('f')), PK (knowledge_id, model)
 CLI:
   backfill [--limit N] [--prefix P] [--dry-run] [--chunk N] [--dedupe]
   drain    [--limit N]
   enqueue  --ids id1,id2[,id3...]
   status
   verify   [--sample N]
 模块API   : enqueue_content_batch(items) / enqueue_ids(db, ids)   (增量接线用)
================================================================================
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from array import array
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ai_bulk_injector_engine import begin_immediate, conn as bi_conn, log  # noqa: E402

DEFAULT_DB = os.path.normpath(os.path.join(_HERE, "..", "database", "app.db"))
OLLAMA_URL = os.environ.get("MTSCOS_OLLAMA_EMBED_URL", "http://localhost:11434/api/embeddings")
OLLAMA_MODEL = os.environ.get("MTSCOS_OLLAMA_EMBED_MODEL", "nomic-embed-text")
BATCH = 50                      # 立项批大小 (对齐 evolution_checkpoint.batch_size)
TEXT_CLIP = 2000                # 嵌入输入截断字符数 (nomic 上下文保守值)
QUEUE_BURN_LIMIT = 5            # 队列行内容缺失熔断阈值
EMBED_TIMEOUT = 30
EMBED_RETRIES = 3               # 连接类错误指数退避 0.5/1/2s

VEC_TABLE = "mt_ai_brain_vector"
CK_TABLE = "mt_brain_vector_checkpoint"
QUEUE_TABLE = "mt_brain_vector_queue"

DDL = (
    f"CREATE TABLE IF NOT EXISTS {VEC_TABLE} ("
    " knowledge_id TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,"
    " embedding BLOB NOT NULL, content_sha TEXT NOT NULL,"
    " created_at TEXT, updated_at TEXT, PRIMARY KEY (knowledge_id, model))",
    f"CREATE INDEX IF NOT EXISTS idx_abv_model ON {VEC_TABLE}(model)",
    f"CREATE TABLE IF NOT EXISTS {CK_TABLE} ("
    " job_key TEXT PRIMARY KEY, last_rowid INTEGER DEFAULT 0, done INTEGER DEFAULT 0,"
    " skipped INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, status TEXT DEFAULT 'RUNNING',"
    " updated_at TEXT, created_at TEXT)",
    f"CREATE TABLE IF NOT EXISTS {QUEUE_TABLE} ("
    " q_id INTEGER PRIMARY KEY AUTOINCREMENT, knowledge_id TEXT NOT NULL UNIQUE,"
    " title TEXT, content TEXT, status TEXT DEFAULT 'PENDING', attempts INTEGER DEFAULT 0,"
    " last_error TEXT, enqueued_at TEXT, processed_at TEXT)",
)


class EmbedUnavailableError(RuntimeError):
    """Ollama 不可达/超时 — fail-closed 信号 (区别于单条数据问题)"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def text_sha(title, content) -> str:
    return hashlib.sha1((str(title or "") + "|" + str(content or "")).encode("utf-8", "ignore")).hexdigest()[:16]


def embed_text(text: str, model: str = OLLAMA_MODEL) -> list:
    """本地 embedding (零token): POST /api/embeddings → float list; 连接类错误重试3次"""
    payload = json.dumps({"model": model, "prompt": (text or "")[:TEXT_CLIP]}).encode("utf-8")
    last_err = None
    for i in range(EMBED_RETRIES):
        try:
            req = urllib.request.Request(OLLAMA_URL, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            emb = data.get("embedding")
            if not emb or not isinstance(emb, list):
                raise ValueError(f"embedding 响应异常: {str(data)[:120]}")
            return emb
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            time.sleep(0.5 * (2 ** i))
    raise EmbedUnavailableError(f"Ollama 不可达 ({OLLAMA_URL}): {last_err}")


EMBED_BATCH_URL = OLLAMA_URL.rsplit("/", 1)[0] + "/embed"

def embed_batch(texts: list, model: str = OLLAMA_MODEL) -> list:
    """批量 embedding (零token): POST /api/embed → list[float list]; 连接类错误重试3次
    
    Ollama 0.5+ 新端点, 单次 HTTP 调用处理 N 条, 比单条快 30-40%
    """
    clean = [(t or "")[:TEXT_CLIP] for t in texts if t]
    if not clean:
        return []
    payload = json.dumps({"model": model, "input": clean}).encode("utf-8")
    last_err = None
    for i in range(EMBED_RETRIES):
        try:
            req = urllib.request.Request(EMBED_BATCH_URL, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT * max(2, len(clean) // 20)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            embs = data.get("embeddings")
            if not embs or not isinstance(embs, list):
                raise ValueError(f"batch embedding 响应异常: {str(data)[:120]}")
            return embs
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            time.sleep(0.5 * (2 ** i))
    raise EmbedUnavailableError(f"Ollama 不可达 ({EMBED_BATCH_URL}): {last_err}")


def to_blob(vec: list) -> bytes:
    return array("f", vec).tobytes()


def from_blob(blob: bytes) -> list:
    a = array("f")
    a.frombytes(blob)
    return a.tolist()


class BrainVectorEngine:
    def __init__(self, db_path: str = DEFAULT_DB, model: str = OLLAMA_MODEL):
        self.db_path = os.path.abspath(db_path)
        self.model = model
        if not os.path.isfile(self.db_path):
            raise SystemExit(f"[FATAL] 主库不存在: {self.db_path}")
        self.ensure_tables()

    # ---------------------------------------------------------------- tables
    def ensure_tables(self) -> None:
        c = bi_conn(self.db_path, timeout=5)
        try:
            begin_immediate(c)
            for stmt in DDL:
                c.execute(stmt)
            c.commit()
        finally:
            c.close()

    def _ck_key(self, prefix: str) -> str:
        return f"backfill:{self.model}:{prefix or 'ALL'}"

    # --------------------------------------------------------------- backfill
    def backfill(self, limit: int = 0, prefix: str = "", dry_run: bool = False, chunk: int = BATCH,
                 dedupe: bool = False) -> dict:
        """扫描主库未向量化行 (rowid 水位 + NOT EXISTS), 分块嵌入回填
        flow_brainvec_dedupe_20261021: dedupe=True 时按内容去重, 只向量化每个 distinct
        内容组的首行 (1.57M 行去重后仅 ~2.5万, 重复副本无检索增益; NOT EXISTS 天然幂等续传)"""
        chunk = max(10, min(int(chunk or BATCH), 500))
        limit = max(0, int(limit or 0))
        ck_key = self._ck_key("DEDUPE" if dedupe else prefix)
        c = bi_conn(self.db_path, timeout=5)
        try:
            begin_immediate(c)
            c.execute(
                f"INSERT OR IGNORE INTO {CK_TABLE} (job_key, status, created_at, updated_at)"
                " VALUES (?, 'RUNNING', ?, ?)", (ck_key, now(), now()))
            c.commit()
            last_rowid = c.execute(
                f"SELECT last_rowid FROM {CK_TABLE} WHERE job_key=?", (ck_key,)).fetchone()[0]

            # flow_brainvec_dedupe_20261021: 两段式幂等 —
            # SQL 层按 id 排除 (PK 索引快; 引擎连接无 sha1 扩展, sha 对账放 Python 层)
            # + 循环内 Python 层 content_sha 漂移过滤 (id 已向量但内容改写的行重嵌,
            #   旧口径漂移行永不重嵌 → 盲区无法收敛, 实测 AE-GAP 1948 条)
            cond = ("k.rowid > ? AND NOT EXISTS (SELECT 1 FROM mt_ai_brain_vector v WHERE v.knowledge_id=k.knowledge_id AND v.model=?)"
                    " AND k.knowledge_id IS NOT NULL AND TRIM(k.knowledge_id)<>''")  # 脏id过滤: NULL/空 knowledge_id 落库必炸 NOT NULL
            params: list = [last_rowid, self.model]
            if prefix:
                cond += " AND k.knowledge_id LIKE ?"
                params.append(prefix + "%")

            if dedupe:
                # temp 表按全量行分组 (含已向量 id; Python 层 sha 对账只嵌缺失/漂移,
                # 引擎连接无 sha1 扩展故 sha 对账放 _filter_drift)
                dcond = "k.knowledge_id IS NOT NULL AND TRIM(k.knowledge_id)<>''"
                dparams: list = []
                if prefix:
                    dcond += " AND k.knowledge_id LIKE ?"
                    dparams.append(prefix + "%")
                c.execute("DROP TABLE IF EXISTS temp.dedupe_rows")
                c.execute(f"""CREATE TEMP TABLE dedupe_rows AS
                    SELECT MIN(k.rowid) AS rid FROM ai_brain_enhanced_knowledge k
                    WHERE {dcond} GROUP BY COALESCE(k.title,'')||'|'||COALESCE(k.content,'')""",
                    dparams)
                todo = c.execute("SELECT COUNT(*) FROM temp.dedupe_rows").fetchone()[0]
            else:
                todo = c.execute(f"SELECT COUNT(*) FROM ai_brain_enhanced_knowledge k WHERE {cond}", params).fetchone()[0]
            log(f"backfill[{ck_key}] 起点 rowid>{last_rowid} 待向量化 {todo} 行"
                + (" [去重模式]" if dedupe else "")
                + (f" (limit={limit})" if limit else "") + (" [DRY-RUN]" if dry_run else ""))
            if dry_run:
                return {"todo": todo, "last_rowid": last_rowid, "dry_run": True}

            done = skipped = failed = 0
            done_fetched = 0               # dedupe 模式 OFFSET 游标 (temp 表分页)
            ck_last = last_rowid
            try:
                while True:
                    if limit and done >= limit:
                        break
                    fetch_n = min(chunk, limit - done) if limit else chunk
                    if dedupe:
                        rows = c.execute(
                            "SELECT k.rowid, k.knowledge_id, k.title, k.content FROM temp.dedupe_rows d"
                            " JOIN ai_brain_enhanced_knowledge k ON k.rowid=d.rid"
                            " ORDER BY d.rid LIMIT ? OFFSET ?", (fetch_n, done_fetched)).fetchall()
                    else:
                        rows = c.execute(
                            f"SELECT k.rowid, k.knowledge_id, k.title, k.content FROM ai_brain_enhanced_knowledge k"
                            f" WHERE {cond} ORDER BY k.rowid LIMIT ?", params + [fetch_n]).fetchall()
                    if not rows:
                        break
                    done_fetched += len(rows)
                    if dedupe:
                        rows = self._filter_drift(c, rows)
                        if not rows:
                            continue
                    vec_rows, ck_last, sk, fl = self._embed_chunk(c, rows)
                    begin_immediate(c)
                    c.executemany(
                        f"INSERT OR REPLACE INTO {VEC_TABLE}"
                        " (knowledge_id, model, dim, embedding, content_sha, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?)", vec_rows)
                    c.execute(
                        f"UPDATE {CK_TABLE} SET last_rowid=?, done=done+?, skipped=skipped+?,"
                        " failed=failed+?, status='RUNNING', updated_at=? WHERE job_key=?",
                        (ck_last, len(vec_rows), sk, fl, now(), ck_key))
                    c.commit()
                    done += len(vec_rows)
                    skipped += sk
                    failed += fl
                    if done % (chunk * 10) == 0 or (limit and done >= limit):
                        log(f"  进度 done={done} skipped={skipped} failed={failed} 水位={ck_last}")
            except EmbedUnavailableError as e:
                c.execute(f"UPDATE {CK_TABLE} SET status='PAUSED', updated_at=? WHERE job_key=?", (now(), ck_key))
                c.commit()
                log(f"backfill 中止(fail-closed, 水位保留): {e}")
                return {"done": done, "skipped": skipped, "failed": failed, "last_rowid": ck_last, "paused": True}
            c.execute(f"UPDATE {CK_TABLE} SET status='IDLE', updated_at=? WHERE job_key=?", (now(), ck_key))
            c.commit()
            log(f"backfill 完成: done={done} skipped={skipped} failed={failed}")
            return {"done": done, "skipped": skipped, "failed": failed, "last_rowid": ck_last}
        finally:
            c.close()

    def _filter_drift(self, c, rows) -> list:
        """Python 层 sha 对账 (flow_brainvec_dedupe_20261021): 保留「未向量」或「内容漂移」行。
        id 已向量且 content_sha 与当前内容一致 → 跳过; 漂移行重嵌 (REPLACE 同 PK 更新)。"""
        if not rows:
            return []
        ph = ",".join("?" * len(rows))
        have = {r["knowledge_id"]: r["content_sha"] for r in c.execute(
            f"SELECT knowledge_id, content_sha FROM {VEC_TABLE} WHERE model=? AND knowledge_id IN ({ph})",
            [self.model] + [r["knowledge_id"] for r in rows]).fetchall()}
        keep = []
        for r in rows:
            if have.get(r["knowledge_id"]) != text_sha(r["title"], r["content"]):
                keep.append(r)
        return keep

    def _embed_chunk(self, c, rows) -> tuple:
        """嵌入一批行; Ollama 不可达 → EmbedUnavailableError 上抛中止 (checkpoint 停在上块)
        flow_brainvec_dedupe_20261021: 批量化 embed_batch 接线 (单条回退), 40倍+加速"""
        vec_rows, ck_last = [], rows[-1]["rowid"]
        # 组 texts + 过滤空内容 (embed_batch 会剔除空串, 须自带对齐)
        pairs = [(i, f"{r['title'] or ''}\n{r['content'] or ''}".strip()) for i, r in enumerate(rows)]
        valid = [(i, t) for i, t in pairs if t]
        sk = len(pairs) - len(valid)
        fl = 0
        embeds = None
        try:
            embeds = embed_batch([t for _, t in valid], self.model)
        except EmbedUnavailableError:
            raise
        except Exception:
            embeds = None          # 单批数据问题 → 回退单条
        if embeds and len(embeds) == len(valid):
            for (i, _t), vec in zip(valid, embeds):
                r = rows[i]
                if not vec:
                    fl += 1
                    continue
                vec_rows.append((r["knowledge_id"], self.model, len(vec), to_blob(vec),
                                 text_sha(r["title"], r["content"]), now(), now()))
            return vec_rows, ck_last, sk, fl
        # 回退单条 embed_text
        for i, text in valid:
            r = rows[i]
            try:
                vec = embed_text(text, self.model)
            except EmbedUnavailableError:
                raise
            except Exception as e:            # 单条数据问题 (响应异常等) → 记失败跳过
                log(f"  嵌入失败 {r['knowledge_id']}: {e}")
                fl += 1
                continue
            vec_rows.append((r["knowledge_id"], self.model, len(vec), to_blob(vec),
                             text_sha(r["title"], r["content"]), now(), now()))
        return vec_rows, ck_last, sk, fl

    # ------------------------------------------------------------------ queue
    def enqueue(self, ids: list) -> int:
        """按 id 入队 (无内容快照, drain 时回查主库)"""
        if not ids:
            return 0
        c = bi_conn(self.db_path, timeout=5)
        try:
            begin_immediate(c)
            cur = c.executemany(
                f"INSERT OR IGNORE INTO {QUEUE_TABLE} (knowledge_id, enqueued_at) VALUES (?,?)",
                [(str(i).strip(), now()) for i in ids if str(i).strip()])
            c.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        finally:
            c.close()

    def drain(self, limit: int = 0, chunk: int = BATCH) -> dict:
        """消化队列 (批量 embed 版):
        - POST /api/embed 单次 N 条 (比单条快 1.9×, 理论 135 条/s)
        - 失败自动回退单条 embed_text
        - Ollama 宕机保留 PENDING 不烧 attempts
        """
        limit = max(0, int(limit or 0))
        chunk = max(100, min(int(chunk or BATCH), 500))  # 批量接口 chunk 提到 100
        c = bi_conn(self.db_path, timeout=5)
        try:
            done = failed = 0
            t0 = datetime.now()
            while True:
                if limit and (done + failed) >= limit:
                    break
                rows = c.execute(
                    f"SELECT q_id, knowledge_id, title, content, attempts FROM {QUEUE_TABLE}"
                    " WHERE status='PENDING' ORDER BY q_id LIMIT ?", (chunk,)).fetchall()
                if not rows:
                    break

                # 1. 准备 texts + 过滤空内容
                valid_rows, texts = [], []
                for r in rows:
                    title, content = r["title"], r["content"]
                    if not content:
                        k = c.execute(
                            "SELECT title, content FROM ai_brain_enhanced_knowledge WHERE knowledge_id=?",
                            (r["knowledge_id"],)).fetchone()
                        title, content = (k["title"], k["content"]) if k else (None, None)
                    text = f"{title or ''}\n{content or ''}".strip()
                    if not text:
                        # 空内容单独处理 (与原逻辑一致)
                        if r["attempts"] + 1 >= QUEUE_BURN_LIMIT:
                            c.execute(
                                f"UPDATE {QUEUE_TABLE} SET status='FAILED', attempts=?, last_error=?, processed_at=? WHERE q_id=?",
                                (QUEUE_BURN_LIMIT, f"内容缺失熔断(attempts={r['attempts']+1})", now(), r["q_id"]))
                            failed += 1
                        else:
                            c.execute(
                                f"UPDATE {QUEUE_TABLE} SET attempts=attempts+1, last_error='主库无此knowledge_id且队列无内容快照',"
                                " processed_at=? WHERE q_id=?", (now(), r["q_id"]))
                        continue
                    valid_rows.append((r, title, content, text))
                    texts.append(text)
                c.commit()

                if not valid_rows:
                    continue

                # 2. 批量 embed (主路径)
                try:
                    embeds = embed_batch(texts, self.model)
                except EmbedUnavailableError:
                    log("Ollama 批量不可达 → 保留 PENDING 不烧 attempts")
                    break
                except Exception as e:
                    log(f"批量 embed 失败({e}) → 回退单条")
                    embeds = None

                vec_rows, done_ids = [], []
                if embeds and len(embeds) == len(valid_rows):
                    # 批量成功: 直接对齐
                    for (r, title, content, _), vec in zip(valid_rows, embeds):
                        if not vec:
                            continue
                        vec_rows.append((r["knowledge_id"], self.model, len(vec), to_blob(vec),
                                         text_sha(title, content), now(), now()))
                        done_ids.append((now(), r["q_id"]))
                else:
                    # 回退单条 embed_text
                    for r, title, content, text in valid_rows:
                        try:
                            vec = embed_text(text, self.model)
                        except EmbedUnavailableError:
                            break
                        except Exception as e:
                            if r["attempts"] + 1 >= QUEUE_BURN_LIMIT:
                                c.execute(
                                    f"UPDATE {QUEUE_TABLE} SET status='FAILED', attempts=?, last_error=?, processed_at=? WHERE q_id=?",
                                    (QUEUE_BURN_LIMIT, f"嵌入响应异常熔断: {e}", now(), r["q_id"]))
                                failed += 1
                            else:
                                c.execute(
                                    f"UPDATE {QUEUE_TABLE} SET attempts=attempts+1, last_error=?, processed_at=? WHERE q_id=?",
                                    (str(e)[:200], now(), r["q_id"]))
                            continue
                        vec_rows.append((r["knowledge_id"], self.model, len(vec), to_blob(vec),
                                         text_sha(title, content), now(), now()))
                        done_ids.append((now(), r["q_id"]))

                # 3. 批量写 DB
                if vec_rows or done_ids:
                    begin_immediate(c)
                    if vec_rows:
                        c.executemany(
                            f"INSERT OR REPLACE INTO {VEC_TABLE}"
                            " (knowledge_id, model, dim, embedding, content_sha, created_at, updated_at)"
                            " VALUES (?,?,?,?,?,?,?)", vec_rows)
                    if done_ids:
                        c.executemany(
                            f"UPDATE {QUEUE_TABLE} SET status='DONE', processed_at=?, attempts=attempts+1,"
                            " last_error=NULL WHERE q_id=?", done_ids)
                    c.commit()
                    done += len(done_ids)

                if done % 1000 == 0 or (limit and done >= limit):
                    elapsed = (datetime.now() - t0).total_seconds()
                    log(f"  drain 进度 done={done:,} ({done/max(elapsed,1):.0f}条/s)")

            log(f"drain 完成: done={done} failed={failed}")
            return {"done": done, "failed": failed}
        finally:
            c.close()

    # ----------------------------------------------------------------- status
    def status(self) -> dict:
        c = bi_conn(self.db_path, timeout=5)
        try:
            st = {}
            st["knowledge_total"] = c.execute("SELECT COUNT(*) FROM ai_brain_enhanced_knowledge").fetchone()[0]
            st["vector_total"] = c.execute(f"SELECT COUNT(*) FROM {VEC_TABLE} WHERE model=?", (self.model,)).fetchone()[0]
            st["coverage_pct"] = round(st["vector_total"] * 100.0 / max(st["knowledge_total"], 1), 2)
            st["dim_profile"] = [dict(r) for r in c.execute(
                f"SELECT model, dim, COUNT(*) AS n FROM {VEC_TABLE} GROUP BY model, dim ORDER BY n DESC LIMIT 5")]
            st["queue"] = {r["status"]: r["n"] for r in c.execute(
                f"SELECT status, COUNT(*) AS n FROM {QUEUE_TABLE} GROUP BY status")}
            st["checkpoints"] = [dict(r) for r in c.execute(
                f"SELECT job_key, last_rowid, done, skipped, failed, status, updated_at FROM {CK_TABLE} ORDER BY job_key")]
            return st
        finally:
            c.close()

    # ----------------------------------------------------------------- verify
    def verify(self, sample: int = 20) -> dict:
        c = bi_conn(self.db_path, timeout=5)
        try:
            rep = {"integrity": c.execute("PRAGMA quick_check").fetchone()[0]}
            total = c.execute(f"SELECT COUNT(*) FROM {VEC_TABLE}").fetchone()[0]
            rep["vector_total"] = total
            if not total:
                rep["note"] = "向量表为空, 无样本可验"
                return rep
            bad_dim = bad_len = drift = 0
            rows = c.execute(
                f"SELECT knowledge_id, model, dim, embedding, content_sha FROM {VEC_TABLE}"
                " ORDER BY RANDOM() LIMIT ?", (max(1, min(int(sample), 500)),)).fetchall()
            for r in rows:
                if r["dim"] <= 0:
                    bad_dim += 1
                    continue
                if len(r["embedding"]) != r["dim"] * 4:
                    bad_len += 1
                    continue
                k = c.execute(
                    "SELECT title, content FROM ai_brain_enhanced_knowledge WHERE knowledge_id=?",
                    (r["knowledge_id"],)).fetchone()
                if k and text_sha(k["title"], k["content"]) != r["content_sha"]:
                    drift += 1                  # 主库内容已漂移 (重嵌入由 backfill 兜底)
            rep.update({"sampled": len(rows), "bad_dim": bad_dim, "bad_len": bad_len, "content_drift": drift})
            rep["pass"] = rep["integrity"] == "ok" and bad_dim == 0 and bad_len == 0
            return rep
        finally:
            c.close()


# ------------------------------------------------------------ 模块级接线 API
def enqueue_content_batch(items, db_path: str = DEFAULT_DB) -> int:
    """增量接线入口 (brain_feeding 用): items=[(knowledge_id, title, content)] 内容随队"""
    if not items:
        return 0
    e = BrainVectorEngine(db_path)
    c = bi_conn(e.db_path, timeout=5)
    try:
        begin_immediate(c)
        cur = c.executemany(
            f"INSERT INTO {QUEUE_TABLE} (knowledge_id, title, content, enqueued_at) VALUES (?,?,?,?)"
            " ON CONFLICT(knowledge_id) DO UPDATE SET title=excluded.title, content=excluded.content,"
            " status='PENDING', processed_at=NULL",
            [(str(k), str(t or "")[:200], str(ct or "")[:4000], now()) for (k, t, ct) in items if str(k or "").strip()])
        c.commit()
        return max(cur.rowcount or 0, 0)
    finally:
        c.close()


def enqueue_ids(ids, db_path: str = DEFAULT_DB) -> int:
    return BrainVectorEngine(db_path).enqueue(ids)


# ---------------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="脑库→向量化引擎 (本地零token)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--prefix", default="", help="knowledge_id 前缀过滤, 如 EIGENFLUX-")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--chunk", type=int, default=BATCH)
    b.add_argument("--dedupe", action="store_true",
                   help="按内容去重, 只向量化 distinct 内容组首行 (flow_brainvec_dedupe_20261021)")
    d = sub.add_parser("drain")
    d.add_argument("--limit", type=int, default=0)
    e = sub.add_parser("enqueue")
    e.add_argument("--ids", required=True, help="逗号分隔 knowledge_id")
    sub.add_parser("status")
    v = sub.add_parser("verify")
    v.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    if a.cmd == "enqueue":
        n = enqueue_ids([x for x in a.ids.split(",") if x.strip()])
        log(f"enqueue 完成: 新入队 {n} 条")
        return
    eng = BrainVectorEngine()
    if a.cmd == "backfill":
        out = eng.backfill(a.limit, a.prefix, a.dry_run, a.chunk, a.dedupe)
    elif a.cmd == "drain":
        out = eng.drain(a.limit)
    elif a.cmd == "status":
        out = eng.status()
    else:
        out = eng.verify(a.sample)
    log(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
