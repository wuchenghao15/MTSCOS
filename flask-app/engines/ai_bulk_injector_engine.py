#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 ai_bulk_injector_engine.py — 泵入式批量数据灌注引擎 (Bulk Injector)
================================================================================
 flow_id   : flow_bulk_injector_engine_20261014   (§14 IRON_RULE 12步骤 STEP_7)
 版本      : v22.20.0 (minor)
 职责      : 将 source 表数据按映射契约分块泵入 target 表 (SQLite → SQLite)
 设计要点  :
   1. 分块事务    : 每 chunk 行 BEGIN IMMEDIATE/COMMIT, 单块提交 < 2s
   2. 双重防重    : NOT EXISTS anti-join 前置过滤(走目标唯一索引) + INSERT OR IGNORE
   3. 断点续传    : 每块提交时同事务落 checkpoint 水位 (严格一致, 不丢不重)
   4. schema 感知 : PRAGMA table_info 感知目标 NOT NULL 列, 缺值回填
                   (声明默认 → *_at 时间戳 → "SYNCED" 占位, 复用 db_triple_sync 方案)
   5. 白名单校验  : 表/列名正则白名单 + sqlite_master 存在性校验, 引擎对业务表零 DDL
   6. 写锁退避    : BEGIN IMMEDIATE 遇 database is locked 指数退避 (0.05s*2^n, 6 次)
   7. ts 碰撞错峰 : q_id/knowledge_id 等秒级时间戳 id 冲突时 +jitter(1.05→1s) 重插
                   (题库教训: 同秒跨题型 OR REPLACE 塌缩)
   8. 脑库投喂    : --feed-brain 完成后自适应写 mt_ai_brain_feed_log
 mapping 契约:
   {
     "columns":   {"src_col": "tgt_col", ...},   # 必填, 列映射 (源列 → 目标列)
     "unique_key": ["tgt_col", ...],             # 可选, anti-join 唯一键 (目标列)
     "ts_col":    "src_col",                     # 可选, 秒级时间戳 id 源列
     "ts_jitter": 1.05                           # 可选, 错峰步长 (取整, 默认 1.05)
   }
 CLI:
   --source S --target T --mapping m.json [--db app.db] [--source-db other.db]
   [--chunk 10000] [--limit N] [--dry-run] [--status] [--verify] [--reset] [--feed-brain]
================================================================================
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(_HERE, "..", "database", "app.db"))

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
BACKOFF_BASE, BACKOFF_TRIES = 0.05, 6          # 0.05+0.1+0.2+0.4+0.8+1.6 = 3.15s
CK_TABLE = "mt_bulk_injector_checkpoint"
CK_DDL = (
    f"CREATE TABLE IF NOT EXISTS {CK_TABLE} ("
    " job_key TEXT PRIMARY KEY, source_table TEXT NOT NULL, target_table TEXT NOT NULL,"
    " pos_col TEXT NOT NULL, last_pos TEXT, injected INTEGER DEFAULT 0,"
    " skipped INTEGER DEFAULT 0, ts_fixed INTEGER DEFAULT 0, status TEXT DEFAULT 'RUNNING',"
    " mapping_sha TEXT, created_at TEXT, updated_at TEXT)"
)
POS_ALIAS = "_bi_pos"


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def safe_ident(name: str, kind: str = "标识符") -> str:
    """白名单校验: 表/列名只允许 [A-Za-z_][A-Za-z0-9_]* — SQL 注入/DDL 关键词全部拦截"""
    if not IDENT_RE.match(name or ""):
        raise SystemExit(f"[FATAL] 非法{kind}: {name!r} (白名单正则拦截)")
    return name


def conn(db_path: str, timeout: float = 2.0) -> sqlite3.Connection:
    c = sqlite3.connect(db_path, timeout=timeout)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=2000")
    return c


def table_exists(c: sqlite3.Connection, table: str) -> bool:
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_cols(c: sqlite3.Connection, table: str) -> Dict[str, Dict[str, Any]]:
    return {r["name"]: dict(r) for r in c.execute(f"PRAGMA table_info({table})")}


def nn_defaults(cols: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """目标表 NOT NULL 列 → 声明默认值 (无默认为 None) — 复用 db_triple_sync 方案"""
    return {n: i["dflt_value"] for n, i in cols.items() if i["notnull"] == 1}


def pos_col_of(c: sqlite3.Connection, table: str) -> str:
    """定序列: 优先 rowid; WITHOUT ROWID 表回退首个主键列"""
    try:
        c.execute(f'SELECT rowid FROM "{table}" LIMIT 1').fetchone()
        return "rowid"
    except sqlite3.OperationalError:
        pks = [n for n, i in table_cols(c, table).items() if i["pk"]]
        if not pks:
            raise SystemExit(f"[FATAL] {table} 无 rowid 且无主键, 无法定序")
        return pks[0]


def has_unique_index(c: sqlite3.Connection, table: str, cols: List[str]) -> bool:
    """uk 列组合是否恰好被某唯一索引覆盖 (决定 anti-join 是否可走索引)"""
    for idx in c.execute(f"PRAGMA index_list('{table}')"):
        if not idx["unique"]:
            continue
        icols = [r["name"] for r in c.execute(f"PRAGMA index_info('{idx['name']}')")]
        if icols == list(cols):
            return True
    return False


def begin_immediate(c: sqlite3.Connection) -> None:
    """拿写锁: 遇 database is locked/busy 指数退避重试"""
    for i in range(BACKOFF_TRIES):
        try:
            c.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e):
                raise
            wait = BACKOFF_BASE * (2 ** i)
            log(f"  写锁忙, 指数退避 {wait:.2f}s (第{i + 1}/{BACKOFF_TRIES}次)")
            time.sleep(wait)
    raise sqlite3.OperationalError("database is locked: 指数退避耗尽")


class BulkInjector:
    def __init__(self, a: argparse.Namespace):
        self.tgt_db = os.path.abspath(a.db)
        self.src_db = os.path.abspath(a.source_db or a.db)
        self.src_t = safe_ident(a.source, "source 表名")
        self.tgt_t = safe_ident(a.target, "target 表名")
        self.chunk = max(100, int(a.chunk))
        self.limit = max(0, int(a.limit or 0))
        self.dry = bool(a.dry_run)
        self.feed = bool(a.feed_brain)
        self.mapping = self._load_mapping(a.mapping)
        self.mapping_sha = hashlib.sha256(
            json.dumps(self.mapping, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    # ---------------------------------------------------------------- mapping
    @staticmethod
    def _load_mapping(path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise SystemExit(f"[FATAL] mapping 文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m.get("columns"), dict) or not m["columns"]:
            raise SystemExit("[FATAL] mapping 缺必填 'columns': {src_col: tgt_col}")
        for s, t in m["columns"].items():
            safe_ident(s, "映射源列")
            safe_ident(t, "映射目标列")
        if m.get("unique_key"):
            uk = m["unique_key"]
            uk = uk if isinstance(uk, list) else [uk]
            m["unique_key"] = [safe_ident(c, "唯一键列") for c in uk]
        if m.get("ts_col"):
            safe_ident(m["ts_col"], "ts_col")
        m["ts_jitter"] = float(m.get("ts_jitter", 1.05))
        return m

    def job_key(self) -> str:
        return f"{self.src_t}->{self.tgt_t}"

    # ------------------------------------------------------------- validation
    def validate(self) -> None:
        """白名单校验: 表存在性 + mapping 列双方存在性 + 定序列探测
        连接保留在 self 上 (src_conn/tgt_conn), 由 run/verify 结束时关闭"""
        for db, t, kind in ((self.src_db, self.src_t, "src"), (self.tgt_db, self.tgt_t, "tgt")):
            if not os.path.isfile(db):
                raise SystemExit(f"[FATAL] {kind} 库不存在: {db}")
            c = conn(db)
            if not table_exists(c, t):
                raise SystemExit(f"[FATAL] {kind} 表不存在: {t} @ {db}")
            setattr(self, f"{kind}_cols", table_cols(c, t))
            setattr(self, f"{kind}_conn", c)
        mcols = self.mapping["columns"]
        miss_s = [s for s in mcols if s not in self.src_cols]
        miss_t = sorted({t for t in mcols.values() if t not in self.tgt_cols})
        uk = self.mapping.get("unique_key") or []
        miss_uk = [c for c in uk if c not in self.tgt_cols]
        if miss_s or miss_t or miss_uk:
            raise SystemExit(
                f"[FATAL] mapping 白名单校验失败: 源缺列{miss_s} 目标缺列{miss_t} 唯一键缺{miss_uk}")
        ts = self.mapping.get("ts_col")
        if ts and ts not in mcols:
            raise SystemExit(f"[FATAL] ts_col '{ts}' 不在 mapping columns 中")
        self.pos_col = pos_col_of(self.src_conn, self.src_t)
        self.uk_ok = bool(uk) and has_unique_index(self.tgt_conn, self.tgt_t, uk)
        log(f"白名单校验通过 | 定序列={self.pos_col} | anti-join="
            f"{'开(走唯一索引)' if self.uk_ok else ('关(uk 无唯一索引, OR IGNORE 兜底)' if uk else '未配置 uk')}")

    def build_plan(self) -> None:
        mcols = self.mapping["columns"]
        self.tgt2src = {t: s for s, t in mcols.items()}
        self.ins_cols = list(dict.fromkeys(mcols.values()))
        self.nn = nn_defaults(self.tgt_cols)
        self.fill_cols = [c for c in self.nn if c not in self.ins_cols]  # NN 缺映射 → 回填
        self.ins_cols += self.fill_cols
        collist = ",".join(f'"{c}"' for c in self.ins_cols)
        ph = ",".join("?" for _ in self.ins_cols)
        self.ins_sql = f'INSERT OR IGNORE INTO "{self.tgt_t}"({collist}) VALUES({ph})'
        if self.uk_ok:
            where = " AND ".join(f'"{c}" IS ?' for c in self.mapping["unique_key"])
            self.uk_sql = f'SELECT 1 FROM "{self.tgt_t}" WHERE {where} LIMIT 1'
        self.ts_tcol = None
        if self.mapping.get("ts_col"):
            self.ts_tcol = mcols[self.mapping["ts_col"]]
            self.ts_step = max(1, int(round(self.mapping["ts_jitter"])))
        if self.fill_cols:
            log(f"schema 感知: NN 缺映射列回填占位 → {self.fill_cols}")

    def fill_nn(self, col: str, d: Optional[str], now: str):
        if d:                                   # 非空声明默认值
            return d.strip("'\"")
        if col.endswith("_at"):                 # 时间戳语义列
            return now
        return "SYNCED"                         # 语义占位

    def build_vals(self, r: sqlite3.Row, now: str) -> List[Any]:
        keys = r.keys()
        vals = []
        for c in self.ins_cols:
            s = self.tgt2src.get(c)
            if s is not None:
                v = r[s] if s in keys else None
                if (v is None or v == "") and c in self.nn:
                    v = self.fill_nn(c, self.nn[c], now)
                vals.append(v)
            else:                               # NN 回填列
                vals.append(self.fill_nn(c, self.nn[c], now))
        return vals

    # ------------------------------------------------------------- checkpoint
    def load_checkpoint(self, c_t: sqlite3.Connection):
        if not table_exists(c_t, CK_TABLE):
            return None, 0, 0
        r = c_t.execute(f"SELECT * FROM {CK_TABLE} WHERE job_key=?",
                        (self.job_key(),)).fetchone()
        if not r:
            return None, 0, 0
        if r["mapping_sha"] and r["mapping_sha"] != self.mapping_sha:
            raise SystemExit("[FATAL] mapping 已变更, 旧水位失效 — 先 --reset 再泵")
        return r["last_pos"], r["injected"] or 0, r["skipped"] or 0

    def ck_upsert(self, c_t: sqlite3.Connection, last_pos: str, n_inj: int,
                  n_skip: int, n_fix: int, status: str, now: str) -> None:
        c_t.execute(
            f"INSERT INTO {CK_TABLE}(job_key,source_table,target_table,pos_col,last_pos,"
            f"injected,skipped,ts_fixed,status,mapping_sha,created_at,updated_at) "
            f"VALUES(?,?,?,?,?,?,?,?,'{status}',?,?,?) "
            f"ON CONFLICT(job_key) DO UPDATE SET last_pos=excluded.last_pos,"
            f"injected={CK_TABLE}.injected+{n_inj},skipped={CK_TABLE}.skipped+{n_skip},"
            f"ts_fixed={CK_TABLE}.ts_fixed+{n_fix},status=excluded.status,"
            f"updated_at=excluded.updated_at",
            (self.job_key(), self.src_t, self.tgt_t, self.pos_col, last_pos,
             n_inj, n_skip, n_fix, self.mapping_sha, now, now))

    # ---------------------------------------------------------------- ts fix
    def try_ts_fix(self, c_t: sqlite3.Connection, vals: List[Any]) -> bool:
        """秒级时间戳 id 冲突错峰: 值 +step 重插 (题库教训 1.05s→取整 1s), 最多 5 次"""
        if not getattr(self, "ts_tcol", None) or self.ts_tcol not in self.ins_cols:
            return False
        i = self.ins_cols.index(self.ts_tcol)
        try:
            v = int(vals[i])
        except (TypeError, ValueError):
            return False
        for _ in range(5):
            v += self.ts_step
            vals2 = list(vals)
            vals2[i] = v
            ch0 = c_t.total_changes
            c_t.execute(self.ins_sql, vals2)
            if c_t.total_changes - ch0 > 0:
                return True
        return False

    # ------------------------------------------------------------------- run
    def run(self) -> Dict[str, Any]:
        self.validate()
        self.build_plan()
        c_s, c_t = self.src_conn, self.tgt_conn
        if self.pos_col == "rowid":
            block_sql = (f'SELECT rowid AS {POS_ALIAS}, * FROM "{self.src_t}" '
                         f"WHERE rowid > ? ORDER BY rowid LIMIT ?")
        else:
            block_sql = (f'SELECT "{self.pos_col}" AS {POS_ALIAS}, * FROM "{self.src_t}" '
                         f'WHERE "{self.pos_col}" > ? ORDER BY "{self.pos_col}" LIMIT ?')
        start_pos, inj0, skip0 = self.load_checkpoint(c_t)
        min_start = "0" if self.pos_col == "rowid" else ""
        if start_pos is None:
            start_pos, status0 = min_start, "新任务"
        else:
            status0 = f"续传@{start_pos} (已注入{inj0}/跳过{skip0})"
        if not self.dry:
            c_t.execute(CK_DDL)               # 基础设施表 (引擎自身运维, 非业务 DDL)
            c_t.commit()
        log(f"任务 {self.job_key()} | chunk={self.chunk} | {status0}"
            + (" | DRY-RUN 零写入" if self.dry else ""))
        t0, total_inj, total_skip, total_fix, nblk = time.time(), 0, 0, 0, 0
        last_pos, done = start_pos, False
        try:
            while True:
                rows = c_s.execute(block_sql, (last_pos, self.chunk)).fetchall()
                if not rows:
                    done = True
                    break
                now = datetime.now().isoformat(timespec="seconds")
                n_inj = n_skip = n_fix = 0
                last_proc = None
                if self.dry:
                    n_inj = len(rows)          # dry-run: 只统计不写入
                else:
                    begin_immediate(c_t)
                    try:
                        seen = set()
                        for r in rows:
                            last_proc = r[POS_ALIAS]
                            if self.uk_ok:
                                k = tuple(r[self.tgt2src[c]] for c in self.mapping["unique_key"])
                                if None not in k:
                                    if k in seen or c_t.execute(self.uk_sql, k).fetchone():
                                        # anti-join 命中: 无 ts 语义 → 跳过; 有 ts 语义 → 错峰重插
                                        if self.ts_tcol and self.try_ts_fix(c_t, self.build_vals(r, now)):
                                            n_inj += 1
                                            n_fix += 1
                                        else:
                                            n_skip += 1
                                        if self.limit and (inj0 + total_inj + n_inj) >= self.limit:
                                            break
                                        continue
                                    seen.add(k)
                            vals = self.build_vals(r, now)
                            ch0 = c_t.total_changes
                            c_t.execute(self.ins_sql, vals)
                            if c_t.total_changes - ch0 == 0:      # 撞唯一约束
                                if self.try_ts_fix(c_t, vals):
                                    n_inj += 1
                                    n_fix += 1
                                else:
                                    n_skip += 1
                                if self.limit and (inj0 + total_inj + n_inj) >= self.limit:
                                    break
                                continue
                            n_inj += 1
                            if self.limit and (inj0 + total_inj + n_inj) >= self.limit:
                                break
                        # checkpoint 与数据块同事务提交 — 断点严格一致 (水位=最后处理行)
                        self.ck_upsert(c_t, str(last_proc if last_proc is not None
                                                else rows[-1][POS_ALIAS]),
                                       n_inj, n_skip, n_fix, "RUNNING", now)
                        c_t.commit()
                    except Exception:
                        c_t.rollback()
                        raise
                last_pos = str(last_proc) if (not self.dry and last_proc is not None) \
                    else str(rows[-1][POS_ALIAS])
                total_inj += n_inj
                total_skip += n_skip
                total_fix += n_fix
                nblk += 1
                rate = (inj0 + total_inj) / max(time.time() - t0, 1e-6)
                log(f"块{nblk}: +{n_inj}注入/{n_skip}跳过/{n_fix}ts错峰 | "
                    f"水位={last_pos} | 累计注入={inj0 + total_inj} | {rate:.0f}行/s")
                if self.limit and (inj0 + total_inj) >= self.limit:
                    log(f"--limit {self.limit} 达到, 暂停 (断点已落库, 重跑即续传)")
                    done = False
                    break
        finally:
            if not self.dry and nblk:
                try:
                    self.ck_status(c_t, "DONE" if done else "RUNNING")
                except sqlite3.Error:
                    pass  # 状态标记失败不吞原始异常
        src_max = c_s.execute(
            f'SELECT MAX({POS_ALIAS}) FROM (SELECT {self.pos_col} AS {POS_ALIAS} '
            f'FROM "{self.src_t}")').fetchone()[0]
        report = {
            "job_key": self.job_key(), "dry_run": self.dry, "pos_col": self.pos_col,
            "chunk": self.chunk, "blocks": nblk,
            "injected_this_run": total_inj, "skipped_this_run": total_skip,
            "ts_fixed_this_run": total_fix,
            "injected_total": inj0 + total_inj, "skipped_total": skip0 + total_skip,
            "last_pos": last_pos, "source_max_pos": str(src_max) if src_max is not None else None,
            "finished": done or bool(self.limit and (inj0 + total_inj) >= self.limit),
            "elapsed_s": round(time.time() - t0, 2), "mapping_sha": self.mapping_sha,
        }
        log(f"完成: {json.dumps(report, ensure_ascii=False)}")
        c_s.close()
        c_t.close()
        if self.feed and not self.dry:
            self.feed_brain(report)
        return report

    def ck_status(self, c_t: sqlite3.Connection, status: str) -> None:
        if table_exists(c_t, CK_TABLE):
            c_t.execute(f"UPDATE {CK_TABLE} SET status=? WHERE job_key=?",
                        (status, self.job_key()))
            c_t.commit()

    # ---------------------------------------------------------------- status
    def status(self) -> None:
        c_t = conn(self.tgt_db)
        r = None
        if table_exists(c_t, CK_TABLE):
            r = c_t.execute(f"SELECT * FROM {CK_TABLE} WHERE job_key=?",
                            (self.job_key(),)).fetchone()
        if not r:
            print(json.dumps({"job_key": self.job_key(), "status": "NO_CHECKPOINT"},
                             ensure_ascii=False))
            return
        out = dict(r)
        try:
            c_s = conn(self.src_db)
            if not getattr(self, "pos_col", None):
                self.pos_col = pos_col_of(c_s, self.src_t)
            out["source_max_pos"] = c_s.execute(
                f'SELECT MAX("{self.pos_col}") FROM "{self.src_t}"').fetchone()[0]
            c_s.close()
        except sqlite3.Error:
            pass
        try:
            if out.get("last_pos") is not None and out.get("source_max_pos") is not None:
                out["progress_pct"] = round(
                    float(out["last_pos"]) / float(out["source_max_pos"]) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        print(json.dumps(out, ensure_ascii=False, default=str))
        c_t.close()

    # ----------------------------------------------------------------- reset
    def reset(self) -> None:
        c_t = conn(self.tgt_db)
        if table_exists(c_t, CK_TABLE):
            n = c_t.execute(f"DELETE FROM {CK_TABLE} WHERE job_key=?",
                            (self.job_key(),)).rowcount
            c_t.commit()
            log(f"checkpoint 已清除 ({n}行): {self.job_key()}")
        else:
            log("无 checkpoint 表, 无需清除")
        c_t.close()

    # ---------------------------------------------------------------- verify
    def verify(self) -> Dict[str, Any]:
        self.validate()
        c_s, c_t = self.src_conn, self.tgt_conn
        src_n = c_s.execute(f'SELECT COUNT(*) FROM "{self.src_t}"').fetchone()[0]
        tgt_n = c_t.execute(f'SELECT COUNT(*) FROM "{self.tgt_t}"').fetchone()[0]
        ck = c_t.execute(f"SELECT * FROM {CK_TABLE} WHERE job_key=?",
                         (self.job_key(),)).fetchone() if table_exists(c_t, CK_TABLE) else None
        uk = self.mapping.get("unique_key") or []
        dup = []
        if uk:
            gcols = ",".join(f'"{c}"' for c in uk)
            dup = [dict(x) for x in c_t.execute(
                f'SELECT {gcols}, COUNT(*) AS n FROM "{self.tgt_t}" '
                f"GROUP BY {gcols} HAVING n > 1 LIMIT 5")]
        spot_ok, spot_bad = 0, 0
        if uk:
            uk_sql = ("SELECT 1 FROM " + f'"{self.tgt_t}" WHERE ' +
                      " AND ".join(f'"{c}" IS ?' for c in uk) + " LIMIT 1")
            mcols = self.mapping["columns"]
            s_of_t = {t: s for s, t in mcols.items()}
            sample = c_s.execute(
                f'SELECT * FROM "{self.src_t}" ORDER BY {self.pos_col} DESC LIMIT 5').fetchall()
            for r in sample:
                k = tuple(r[s_of_t[c]] for c in uk)
                if c_t.execute(uk_sql, k).fetchone():
                    spot_ok += 1
                else:
                    spot_bad += 1
        report = {
            "job_key": self.job_key(),
            "source_rows": src_n, "target_rows": tgt_n,
            "checkpoint": dict(ck) if ck else None,
            "uk_duplicate_samples": dup,
            "spot_check": {"ok": spot_ok, "bad": spot_bad},
            "pass": not dup and spot_bad == 0,
        }
        log(f"VERIFY {'PASS' if report['pass'] else 'FAIL'}: "
            f"{json.dumps(report, ensure_ascii=False, default=str)}")
        c_s.close()
        c_t.close()
        return report

    # ------------------------------------------------------------- feed brain
    def feed_brain(self, report: Dict[str, Any]) -> None:
        """可选: 灌注报告自适应写 AI 脑库 (仅插目标库中真实存在的列)"""
        c = conn(self.tgt_db)
        try:
            if not table_exists(c, "mt_ai_brain_feed_log"):
                log("脑库表 mt_ai_brain_feed_log 不存在, 跳过投喂")
                return
            cols = table_cols(c, "mt_ai_brain_feed_log")
            now = datetime.now().isoformat(timespec="seconds")
            cand = {
                "feed_type": "bulk_injector_report",
                "content": json.dumps(report, ensure_ascii=False)[:2000],
                "summary": f"泵入 {report.get('injected_this_run', 0)} 行 → {self.tgt_t}",
                "source": "ai_bulk_injector_engine",
                "flow_id": "flow_bulk_injector_engine_20261014",
                "created_at": now, "updated_at": now,
            }
            use = {k: v for k, v in cand.items() if k in cols}
            nn = nn_defaults(cols)
            for c2, d in nn.items():
                if c2 not in use:
                    use[c2] = self.fill_nn(c2, d, now)
            collist = ",".join(f'"{k}"' for k in use)
            ph = ",".join("?" for _ in use)
            c.execute(f"INSERT INTO mt_ai_brain_feed_log({collist}) VALUES({ph})",
                      tuple(use.values()))
            c.commit()
            log(f"脑库投喂完成: {list(use.keys())}")
        finally:
            c.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="泵入式批量数据灌注引擎 (分块事务+防重+断点续传)")
    ap.add_argument("--source", required=True, help="源表名")
    ap.add_argument("--target", required=True, help="目标表名")
    ap.add_argument("--mapping", required=True, help="mapping 契约 JSON 文件")
    ap.add_argument("--db", default=DEFAULT_DB, help="目标库 (默认 database/app.db)")
    ap.add_argument("--source-db", default=None, help="源库 (默认同 --db)")
    ap.add_argument("--chunk", type=int, default=10000, help="块大小 (默认 10000)")
    ap.add_argument("--limit", type=int, default=0, help="本次最多注入行数 (0=不限)")
    ap.add_argument("--dry-run", action="store_true", help="演练: 零写入")
    ap.add_argument("--status", action="store_true", help="查看 checkpoint 进度")
    ap.add_argument("--verify", action="store_true", help="抽验一致性")
    ap.add_argument("--reset", action="store_true", help="清除 checkpoint 重来")
    ap.add_argument("--feed-brain", action="store_true", help="完成后投喂 AI 脑库")
    a = ap.parse_args()
    eng = BulkInjector(a)
    if a.status:
        eng.status()
    elif a.reset:
        eng.reset()
    elif a.verify:
        sys.exit(0 if eng.verify()["pass"] else 1)
    else:
        eng.run()


if __name__ == "__main__":
    main()
