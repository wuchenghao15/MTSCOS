#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v23.0.0 baseline 幂等数据库迁移
==============================

冰山系统 v22.x -> v23.0.0 大版本升级的结构基线。沿用项目既有约定
(运行时 CREATE TABLE IF NOT EXISTS / PRAGMA 守卫的 ALTER), 不引入 alembic:
活库 2.3GB 且表均为运行中自然演化, alembic stamp 不校验真实 schema、噪音大。

本脚本只做"补列/建审计表", 不改任何既有业务表数据, 可安全重复执行:
  1. mt_schema_revisions            迁移标记表 (alembic 式审计, 幂等闸门)
  2. mt_ai_suggestion_pool          补 evaluated_at 列 (修复 collect_suggestions L2335 写不存在列)
  3. mt_research_implementations    自探研提案衍生产物登记 (RESEARCH_DERIVE 消费闭环)
  4. system_versions                系统版本发布行 (列对齐 get_version_info 的 SELECT)

目标库: flask-app/database/app.db (演化/Flask 主库)。
兼容 /usr/bin/python3 (3.9): 不用 match/联合类型/f-string 反斜杠。

用法:
    /usr/bin/python3 scripts/migrations/v23_0_0_baseline.py          # 执行
    /usr/bin/python3 scripts/migrations/v23_0_0_baseline.py --check  # 只检查不写
"""
import os
import sqlite3
import sys
import time

REVISION = "v23.0.0_baseline"

# scripts/migrations/v23.. -> 上溯三级 = flask-app/
FLASK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(FLASK_ROOT, "database", "app.db")


def table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def column_exists(conn, table, column):
    for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall():
        if row[1] == column:
            return True
    return False


def mark_revision(conn, note):
    conn.execute(
        "INSERT OR IGNORE INTO mt_schema_revisions(revision, applied_at, note) VALUES (?,?,?)",
        (REVISION, time.strftime("%Y-%m-%d %H:%M:%S"), note),
    )


def main():
    check_only = "--check" in sys.argv

    if not os.path.exists(DB_PATH):
        print("[FATAL] 找不到数据库: %s" % DB_PATH)
        return 2

    print("[v23-migrate] DB = %s (%.0f MB)" % (DB_PATH, os.path.getsize(DB_PATH) / 1048576.0))
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")

    # 0) 迁移标记表 (本身也要幂等)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mt_schema_revisions(
               revision   TEXT PRIMARY KEY,
               applied_at TEXT,
               note       TEXT
           )"""
    )
    conn.commit()

    applied = conn.execute(
        "SELECT 1 FROM mt_schema_revisions WHERE revision=?", (REVISION,)
    ).fetchone()
    if applied:
        print("[v23-migrate] revision=%s 已应用, 整体跳过 (幂等)" % REVISION)
        # 即便已标记, 仍核对对象齐全 (防止历史上半截失败却打了标)
        _report(conn)
        conn.close()
        return 0

    if check_only:
        print("[v23-migrate] --check 模式: revision 尚未应用")
        _report(conn)
        conn.close()
        return 1

    results = []  # (name, status, detail)

    def step(name, fn):
        try:
            detail = fn(conn)
            results.append((name, "OK", detail or ""))
            print("  [OK] %s %s" % (name, detail or ""))
        except Exception as exc:  # 每条 DDL 独立, 单点失败不回滚已成功项 (SQLite DDL 非事务性)
            results.append((name, "FAIL", str(exc)[:200]))
            print("  [FAIL] %s -> %s" % (name, exc))

    # 1) mt_ai_suggestion_pool.evaluated_at
    def s_evaluated_at(c):
        if not table_exists(c, "mt_ai_suggestion_pool"):
            return "表不存在, 跳过"
        if column_exists(c, "mt_ai_suggestion_pool", "evaluated_at"):
            return "evaluated_at 已存在"
        c.execute("ALTER TABLE mt_ai_suggestion_pool ADD COLUMN evaluated_at TEXT")
        return "已 ADD COLUMN evaluated_at"
    step("mt_ai_suggestion_pool.evaluated_at", s_evaluated_at)

    # 2) mt_research_implementations
    def s_impl(c):
        c.execute(
            """CREATE TABLE IF NOT EXISTS mt_research_implementations(
                   impl_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                   prop_id       TEXT,
                   suggestion_id INTEGER,
                   artifact_type TEXT,
                   artifact_path TEXT,
                   status        TEXT,
                   attempts      INTEGER DEFAULT 0,
                   error         TEXT,
                   flow_id       TEXT,
                   created_at    TEXT,
                   updated_at    TEXT
               )"""
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_impl_prop ON mt_research_implementations(prop_id)"
        )
        return "mt_research_implementations 就绪"
    step("mt_research_implementations", s_impl)

    # 3) system_versions (列对齐 server_real_db.get_version_info 的 SELECT)
    def s_sysver(c):
        if table_exists(c, "system_versions"):
            return "system_versions 已存在, 不重建"
        c.execute(
            """CREATE TABLE IF NOT EXISTS system_versions(
                   id           INTEGER PRIMARY KEY AUTOINCREMENT,
                   version      TEXT,
                   codename     TEXT,
                   build_number TEXT,
                   build_date   TEXT,
                   status       TEXT,
                   description  TEXT,
                   created_at   TEXT
               )"""
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_system_versions_ver ON system_versions(version)"
        )
        return "system_versions 就绪"
    step("system_versions", s_sysver)

    # 仅当没有 FAIL 时才打 revision 标记; 有失败保留未标记, 允许修复后重跑
    fails = [r for r in results if r[1] == "FAIL"]
    if not fails:
        mark_revision(conn, "baseline: evaluated_at + research_implementations + system_versions")
        print("[v23-migrate] 已打标记 revision=%s" % REVISION)
    else:
        print("[v23-migrate] %d 步失败, 不打 revision 标记, 请修复后重跑" % len(fails))

    conn.commit()
    _report(conn)
    conn.close()
    return 0 if not fails else 3


def _report(conn):
    try:
        pool_cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_ai_suggestion_pool)")]
        print("[v23-migrate] -- 现状 --")
        print("  mt_ai_suggestion_pool.evaluated_at : %s"
              % ("有" if "evaluated_at" in pool_cols else "无"))
        print("  mt_research_implementations        : %s"
              % ("有" if table_exists(conn, "mt_research_implementations") else "无"))
        print("  system_versions                    : %s"
              % ("有" if table_exists(conn, "system_versions") else "无"))
    except Exception as exc:
        print("[v23-migrate] report 失败: %s" % exc)


if __name__ == "__main__":
    sys.exit(main())
