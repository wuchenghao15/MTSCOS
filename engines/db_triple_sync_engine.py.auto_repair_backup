# -*- coding: utf-8 -*-
"""
P3: app.db 三方同步引擎 (§14 flow 表一致性保障)
================================================
背景: 项目存在多份活跃 app.db 副本, §14 flow 表数据发散,
      曾导致 commit-msg hook 在 hook 库中查不到 flow_id 而误杀合法 commit。

拓扑 (flow_db_triple_sync_20261013):
  PRIMARY  = flask-app/database/app.db        (主库: Flask APP_DB + git hooks, flows 最多)
  MIRRORS  = 项目根 ./app.db, flask-app/engines/app.db

同步表 (§14 执行链关键小表, 行数小):
  - mt_dev_flow_session     合并策略: flow_id 为键, newest-wins (updated_at→created_at)
  - mt_dev_flow_events      合并策略: 内容指纹去重 (不复制自增 ev_id, 只补缺失)
  - mt_iron_rule_violations 合并策略: 内容指纹去重 (不复制自增 viol_id, 只补缺失)

安全设计:
  - 只同步三库共有的列交集 (三库 schema 有漂移, 各库私有列不动)
  - session 用逐行 UPDATE/INSERT, 旧库不会被新库多余列抹掉数据
  - events/violations 永不 REPLACE, 只补缺失指纹 → 幂等
  - 每次同步落库 mt_db_sync_log (三库各记一份)

CLI:
  python3 db_triple_sync_engine.py status          # 三库统计 + 差异报告
  python3 db_triple_sync_engine.py sync            # 执行三方合并
  python3 db_triple_sync_engine.py verify          # 同步后一致性校验
"""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_ENGINES_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP_DIR = os.path.dirname(_ENGINES_DIR)
_PROJECT_ROOT = os.path.dirname(_FLASK_APP_DIR)

# 三方拓扑: PRIMARY + MIRRORS
PRIMARY_DB = os.path.join(_FLASK_APP_DIR, "database", "app.db")
MIRROR_DBS = [
    os.path.join(_PROJECT_ROOT, "app.db"),
    os.path.join(_FLASK_APP_DIR, "engines", "app.db"),
]
ALL_DBS = [PRIMARY_DB] + MIRROR_DBS

# 同步的表 (§14 执行链)
_SYNC_TABLES = ("mt_dev_flow_session", "mt_dev_flow_events", "mt_iron_rule_violations")

# session 行新旧比较键 (依次取第一个非空)
_SESSION_TS_COLS = ("updated_at", "created_at")


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _table_cols(db_path: str, table: str) -> List[str]:
    try:
        conn = _conn(db_path)
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        conn.close()
        return cols
    except Exception:
        return []


def _common_cols(table: str) -> List[str]:
    """三库列交集 (保持 PRAGMA 顺序, 以主库顺序为准)"""
    primary_cols = _table_cols(PRIMARY_DB, table)
    common = set(primary_cols)
    for db in MIRROR_DBS:
        common &= set(_table_cols(db, table))
    return [c for c in primary_cols if c in common]


def _parse_ts(value: Optional[str]) -> str:
    """时间戳归一化用于比较 (ISO 'T' 与空格格式混用)"""
    if not value:
        return ""
    return str(value).replace("T", " ")


def _row_ts(row: sqlite3.Row) -> str:
    for col in _SESSION_TS_COLS:
        if col in row.keys() and row[col]:
            return _parse_ts(row[col])
    return ""


def _ensure_sync_log_table(db_path: str) -> None:
    conn = _conn(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mt_db_sync_log ("
        "log_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "run_id TEXT, synced_at TEXT, table_name TEXT, target_db TEXT,"
        "inserted INTEGER DEFAULT 0, updated INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0,"
        "note TEXT)"
    )
    conn.commit()
    conn.close()


def _fingerprint_event(row: sqlite3.Row) -> Tuple:
    keys = row.keys()
    return (
        (row["flow_id"] or "") if "flow_id" in keys else "",
        (row["event_kind"] or "") if "event_kind" in keys else "",
        (row["from_step"] or "") if "from_step" in keys else "",
        (row["to_step"] or "") if "to_step" in keys else "",
        ((row["triggered_by"] or "") if "triggered_by" in keys else ""),
        _parse_ts(row["triggered_at"] if "triggered_at" in keys else ""),
    )


def _fingerprint_violation(row: sqlite3.Row) -> Tuple:
    """violations 身份键 = (flow_id, viol_rule) — 三库交集列, 异构 schema 稳定。
    语义: 每库每 (flow, rule) 保留一条权威记录 (主库→镜像单向)"""
    keys = row.keys()
    return (
        (row["flow_id"] or "") if "flow_id" in keys else "",
        (row["viol_rule"] or "") if "viol_rule" in keys else "",
    )


def _load_rows(db_path: str, table: str, cols: Optional[List[str]] = None) -> List[sqlite3.Row]:
    conn = _conn(db_path)
    sel = f"SELECT {','.join(cols)} FROM {table}" if cols else f"SELECT * FROM {table}"
    rows = conn.execute(sel).fetchall()
    conn.close()
    return rows


def _v(row: sqlite3.Row, col: str):
    """NULL→空串归一 (镜像库 NOT NULL 约束兼容)"""
    val = row[col] if col in row.keys() else None
    return "" if val is None else val


def _target_nn_defaults(db_path: str, table: str) -> Dict[str, Optional[str]]:
    """目标表 NOT NULL 列 → 声明的默认值 (无默认为 None)"""
    conn = _conn(db_path)
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {r["name"]: r["dflt_value"] for r in info if r["notnull"] == 1}


def _make_valuer(src: sqlite3.Row, nn: Dict[str, Optional[str]]):
    """目标库感知取值器: NOT NULL 列空值时回填 (声明默认 → 时间戳 → 语义占位)"""
    keys = src.keys()
    now = datetime.now().isoformat(timespec="seconds")

    def val(col: str):
        v = _v(src, col)
        if v != "" or col not in nn:
            return v
        d = nn[col]
        if d:  # 非空声明默认值 (PRAGMA 空串/NULL 都视为无默认)
            return d.strip("'\"")
        if col.endswith("_at"):
            return now
        if col == "viol_code":
            rule = src["viol_rule"] if "viol_rule" in keys else None
            return rule or "UNKNOWN"
        # 其余 NOT NULL 无默认列 (viol_stage/viol_action/未知) → 同步占位
        return "SYNCED"

    return val


def _upsert_session(target_db: str, source_rows: List[sqlite3.Row], cols: List[str]) -> Dict[str, int]:
    """session 逐行 upsert: 缺失→INSERT, 目标较旧→UPDATE (newest-wins)"""
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    conn = _conn(target_db)
    tgt = {r["flow_id"]: r for r in conn.execute(
        f"SELECT {','.join(cols)} FROM mt_dev_flow_session").fetchall()}
    col_list = ",".join(cols)
    ph = ",".join("?" for _ in cols)
    set_clause = ",".join(f"{c}=?" for c in cols if c != "flow_id")
    for src in source_rows:
        fid = src["flow_id"]
        local = tgt.get(fid)
        if local is None:
            # 目标 NOT NULL 列若不在三库交集, 需追加进 INSERT 列 (valuer 回填)
            nn_s = _target_nn_defaults(target_db, "mt_dev_flow_session")
            ins_cols = list(cols) + [c for c in nn_s if c not in cols]
            val = _make_valuer(src, nn_s)
            conn.execute(
                f"INSERT INTO mt_dev_flow_session({','.join(ins_cols)}) "
                f"VALUES({','.join('?' for _ in ins_cols)})",
                tuple(val(c) for c in ins_cols),
            )
            stats["inserted"] += 1
        elif _row_ts(src) > _row_ts(local):
            conn.execute(
                f"UPDATE mt_dev_flow_session SET {set_clause} WHERE flow_id=?",
                tuple(_v(src, c) for c in cols if c != "flow_id") + (fid,),
            )
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    conn.commit()
    conn.close()
    return stats


def _insert_missing(target_db: str, table: str, source_rows: List[sqlite3.Row],
                    cols: Optional[List[str]], fp_fn) -> Dict[str, int]:
    """events/violations: 指纹去重, 只补缺失 (幂等)
    源行为全列行; 插入列 = 目标全列 - 自增列 (源缺列由 valuer 回填)"""
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    conn = _conn(target_db)
    existing = set()
    for r in conn.execute(f"SELECT * FROM {table}").fetchall():
        existing.add(fp_fn(r))
    t_cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    auto = ("ev_id", "viol_id")
    ins_cols = [c for c in t_cols if c not in auto]
    nn = _target_nn_defaults(target_db, table)
    col_list = ",".join(ins_cols)
    ph = ",".join("?" for _ in ins_cols)
    for src in source_rows:
        fp = fp_fn(src)
        if fp in existing:
            stats["skipped"] += 1
            continue
        val = _make_valuer(src, nn)
        conn.execute(
            f"INSERT INTO {table}({col_list}) VALUES({ph})",
            tuple(val(c) for c in ins_cols),
        )
        existing.add(fp)
        stats["inserted"] += 1
    conn.commit()
    conn.close()
    return stats


def sync_all(dry_run: bool = False) -> Dict:
    """执行三方双向合并"""
    run_id = f"sync_{uuid.uuid4().hex[:12]}"
    started = datetime.now().isoformat(timespec="seconds")
    report: Dict = {"run_id": run_id, "started": started, "dry_run": dry_run, "tables": {}}

    for table in _SYNC_TABLES:
        cols = _common_cols(table)
        if not cols:
            report["tables"][table] = {"error": "无共有列"}
            continue
        # 汇集三方全量行 (每个源库贡献自己的行)
        pool: Dict[str, sqlite3.Row] = {}
        if table == "mt_dev_flow_session":
            for db in ALL_DBS:
                for row in _load_rows(db, table, cols):
                    # newest-wins 汇集: 同 flow_id 取时间戳最新行 (并列时先读者=主库优先)
                    _ex = pool.get(row["flow_id"])
                    if _ex is None or _row_ts(row) > _row_ts(_ex):
                        pool[row["flow_id"]] = row
            table_stats = {}
            for db in ALL_DBS:
                table_stats[os.path.relpath(db, _PROJECT_ROOT)] = (
                    {"dry_run": True, "would_upsert": len(pool)} if dry_run
                    else _upsert_session(db, list(pool.values()), cols)
                )
        else:
            fp_fn = _fingerprint_event if table == "mt_dev_flow_events" else _fingerprint_violation
            if table == "mt_iron_rule_violations":
                # violations: 主库→镜像 单向权威日志 (异构 schema 下指纹下行失真, 不可双向)
                pool_rows = _load_rows(PRIMARY_DB, table)
                seen: set = set()
                unique_rows: List[sqlite3.Row] = []
                for row in pool_rows:
                    fp = fp_fn(row)
                    if fp not in seen:
                        seen.add(fp)
                        unique_rows.append(row)
                targets = MIRROR_DBS
            else:
                seen: set = set()
                unique_rows: List[sqlite3.Row] = []
                for db in ALL_DBS:
                    for row in _load_rows(db, table):  # 全列加载, 指纹保真
                        fp = fp_fn(row)
                        if fp not in seen:
                            seen.add(fp)
                            unique_rows.append(row)
                targets = ALL_DBS
            table_stats = {}
            for db in targets:
                table_stats[os.path.relpath(db, _PROJECT_ROOT)] = (
                    {"dry_run": True, "would_insert": len(unique_rows)} if dry_run
                    else _insert_missing(db, table, unique_rows, cols, fp_fn)
                )
        report["tables"][table] = {"common_cols": len(cols), "dbs": table_stats}

    report["finished"] = datetime.now().isoformat(timespec="seconds")
    if not dry_run:
        rel = os.path.relpath(PRIMARY_DB, _PROJECT_ROOT)
        for db in ALL_DBS:
            try:
                _ensure_sync_log_table(db)
                conn = _conn(db)
                for tname, tinfo in report["tables"].items():
                    if "error" in tinfo:
                        continue
                    agg = {"inserted": 0, "updated": 0, "skipped": 0}
                    for dstats in tinfo["dbs"].values():
                        for k in agg:
                            agg[k] += dstats.get(k, 0)
                    conn.execute(
                        "INSERT INTO mt_db_sync_log(run_id, synced_at, table_name, target_db,"
                        " inserted, updated, skipped, note) VALUES(?,?,?,?,?,?,?,?)",
                        (run_id, report["finished"], tname, rel,
                         agg["inserted"], agg["updated"], agg["skipped"], "triple_sync"),
                    )
                conn.commit()
                conn.close()
            except Exception as e:
                report.setdefault("log_errors", []).append(f"{db}: {e}")
    return report


def status() -> Dict:
    """三库 flow 表统计 + 差异"""
    out: Dict = {"primary": os.path.relpath(PRIMARY_DB, _PROJECT_ROOT), "mirrors": [], "tables": {}}
    for table in _SYNC_TABLES:
        counts = {}
        for db in ALL_DBS:
            try:
                conn = _conn(db)
                counts[os.path.relpath(db, _PROJECT_ROOT)] = conn.execute(
                    f"SELECT count(*) FROM {table}").fetchone()[0]
                conn.close()
            except Exception as e:
                counts[os.path.relpath(db, _PROJECT_ROOT)] = f"ERR:{e}"
        out["tables"][table] = counts
    # flow 级发散 (session)
    try:
        per_db: Dict[str, Dict[str, Tuple[str, str]]] = {}
        for db in ALL_DBS:
            conn = _conn(db)
            rel = os.path.relpath(db, _PROJECT_ROOT)
            per_db[rel] = {r["flow_id"]: (r["current_step"] or "", r["final_status"] or "")
                           for r in conn.execute(
                               "SELECT flow_id, current_step, final_status FROM mt_dev_flow_session")}
            conn.close()
        all_fids = set()
        for m in per_db.values():
            all_fids |= set(m)
        divergent = []
        for fid in sorted(all_fids):
            states = {rel: per_db[rel].get(fid) for rel in per_db}
            vals = {v for v in states.values() if v is not None}
            if len(vals) > 1 or any(v is None for v in states.values()):
                divergent.append({"flow_id": fid, "states": {k: v for k, v in states.items()}})
        out["session_divergence_count"] = len(divergent)
        out["session_divergence_sample"] = divergent[:10]
    except Exception as e:
        out["session_divergence_error"] = str(e)
    return out


def verify() -> Dict:
    """同步后一致性校验: 三库同表行数一致 + 指纹集合一致"""
    result: Dict = {"pass": True, "tables": {}}
    for table in _SYNC_TABLES:
        fp_fn = None
        if table == "mt_dev_flow_events":
            fp_fn = _fingerprint_event
        elif table == "mt_iron_rule_violations":
            fp_fn = _fingerprint_violation
        sets = {}
        for db in ALL_DBS:
            rows = _load_rows(db, table)  # 全列加载, 指纹保真
            if fp_fn:
                sets[os.path.relpath(db, _PROJECT_ROOT)] = {fp_fn(r) for r in rows}
            else:
                sets[os.path.relpath(db, _PROJECT_ROOT)] = {r["flow_id"] for r in rows}
        union = set().union(*sets.values())
        missing = {}
        if table == "mt_iron_rule_violations":
            # 单向权威日志: 只要求镜像 ⊆ 主库 (主库可含额外历史键)
            pkey = os.path.relpath(PRIMARY_DB, _PROJECT_ROOT)
            for rel, s in sets.items():
                if rel == pkey:
                    continue
                diff = sets[pkey] - s
                if diff:
                    missing[rel] = len(diff)
        else:
            for rel, s in sets.items():
                diff = union - s
                if diff:
                    missing[rel] = len(diff)
        ok = not missing
        result["tables"][table] = {"consistent": ok, "missing": missing}
        if not ok:
            result["pass"] = False
    return result


def _cli(argv: List[str]) -> int:
    import json
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2, default=str))
        return 0
    if cmd == "sync":
        dry = "--dry-run" in argv
        rep = sync_all(dry_run=dry)
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0
    if cmd == "verify":
        v = verify()
        print(json.dumps(v, ensure_ascii=False, indent=2, default=str))
        return 0 if v["pass"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))

# auto_repair: ensure env-first PROD DB
try:
    from engines._common.db_resolver import get_app_db
    APP_DB = get_app_db()
except Exception:
    pass
