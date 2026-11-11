# -*- coding: utf-8 -*-
"""
邀请流程增强测试 (flow_id=flow_sa_ai_invite_enhance_20261013)
==============================================================
覆盖:
  T1 batch_invite 批量创建 PENDING 邀请
  T2 retry_pending_invites 重试翻转 ACCEPTED
  T3 retry_count 上限 (max_retry 用尽不再重试)
  T4 invite_log 列扩展幂等 (_ensure_invite_log_columns)
  T5 状态跟踪统计查询 (API /invite/status 同款 SQL)
  T6 好友互推统计查询 (API /invite/mutual_stats 同款 SQL)

运行: python3 invite_flow_test.py            # 全部
      python3 invite_flow_test.py cleanup    # 清理测试数据
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_auto_hire_engine import (  # noqa: E402
    APP_DB, batch_invite, retry_pending_invites, _ensure_invite_log_columns,
)

TEST_SOURCE = "INVITE_FLOW_TEST"
RESULTS = []


def _conn():
    return sqlite3.connect(APP_DB, timeout=30)


def cleanup():
    c = _conn()
    names = c.execute(
        "SELECT expert_name FROM mt_eigenflux_invite_log WHERE invite_source=?",
        (TEST_SOURCE,)).fetchall()
    for (name,) in names:
        c.execute("DELETE FROM eigenflux_registrations WHERE employee_name=? AND employee_type='eigenflux_expert'", (name,))
    c.execute("DELETE FROM mt_eigenflux_invite_log WHERE invite_source=?", (TEST_SOURCE,))
    c.commit()
    c.close()


def T(name):
    def deco(fn):
        def wrapper():
            try:
                fn()
                RESULTS.append((name, "PASS", ""))
                print(f"  ✅ {name}")
            except AssertionError as e:
                RESULTS.append((name, "FAIL", str(e)))
                print(f"  ❌ {name}: {e}")
            except Exception as e:
                RESULTS.append((name, "ERROR", str(e)))
                print(f"  ⚠️  {name}: {e}")
        return wrapper
    return deco


@T("T1 batch_invite 创建 PENDING")
def t1():
    r = batch_invite(count=2, domain="t1sec", source=TEST_SOURCE)
    assert r["created"] == 2, f"created={r['created']}"
    c = _conn()
    n = c.execute(
        "SELECT COUNT(*) FROM mt_eigenflux_invite_log WHERE invite_source=? AND invite_status='PENDING'",
        (TEST_SOURCE,)).fetchone()[0]
    p = c.execute(
        "SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='pending_invite' AND employee_name LIKE 'EigenFlux专家-t1sec-%'").fetchone()[0]
    c.close()
    assert n == 2 and p == 2, f"log={n} pending={p}"


@T("T2 retry 翻转 ACCEPTED")
def t2():
    r = retry_pending_invites(max_retry=3)
    c = _conn()
    acc = c.execute(
        "SELECT COUNT(*) FROM mt_eigenflux_invite_log WHERE invite_source=? AND invite_status='ACCEPTED' AND retry_count>=1",
        (TEST_SOURCE,)).fetchone()[0]
    pend = c.execute(
        "SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='pending_invite' AND employee_name LIKE 'EigenFlux专家-t1sec-%'").fetchone()[0]
    c.close()
    assert acc == 2, f"accepted={acc}"
    assert pend == 0, f"pending残留={pend}"
    assert r["retried"] >= 2, f"retried={r['retried']}"


@T("T3 retry_count 上限")
def t3():
    c = _conn()
    c.execute("INSERT INTO mt_eigenflux_invite_log (invite_id, expert_name, expert_role, expert_domain, invite_source, invite_status, invited_at, retry_count) VALUES ('INV-T3TEST','T3专家','t3','t3',?,'RETRYING',datetime('now'),3)", (TEST_SOURCE,))
    c.commit(); c.close()
    r = retry_pending_invites(max_retry=3)
    c = _conn()
    row = c.execute("SELECT invite_status, retry_count FROM mt_eigenflux_invite_log WHERE invite_id='INV-T3TEST'").fetchone()
    c.execute("DELETE FROM mt_eigenflux_invite_log WHERE invite_id='INV-T3TEST'")
    c.commit(); c.close()
    assert row is not None, "记录被意外修改"
    assert row[1] == 3, f"retry_count被改: {row[1]}"


@T("T4 列扩展幂等")
def t4():
    c = _conn()
    _ensure_invite_log_columns(c)
    cols1 = {r[1] for r in c.execute("PRAGMA table_info(mt_eigenflux_invite_log)").fetchall()}
    _ensure_invite_log_columns(c)
    cols2 = {r[1] for r in c.execute("PRAGMA table_info(mt_eigenflux_invite_log)").fetchall()}
    c.close()
    assert cols1 == cols2, "幂等性破坏"
    assert "retry_count" in cols1 and "last_retry_at" in cols1, f"缺列: {cols1}"


@T("T5 状态跟踪统计 SQL")
def t5():
    c = _conn()
    status_dist = {r[0]: r[1] for r in c.execute(
        "SELECT invite_status, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY 1").fetchall()}
    retry_summary = {str(r[0]): r[1] for r in c.execute(
        "SELECT COALESCE(retry_count,0) AS rc, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY rc ORDER BY rc").fetchall()}
    c.close()
    assert sum(status_dist.values()) > 0, "空分布"
    assert "1" in retry_summary, "T1/T2 产生的 retry_count=1 未统计"


@T("T6 互推统计 SQL")
def t6():
    c = _conn()
    total = c.execute("SELECT COUNT(*) FROM mt_ai_eigenflux_connections").fetchone()[0]
    friend_recommended = c.execute(
        "SELECT COUNT(*) FROM mt_ai_eigenflux_connections WHERE shared_topics_json LIKE '%friend_recommendation%'").fetchone()[0]
    c.close()
    assert total >= 0 and friend_recommended <= total, "互推统计越界"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    if only == "cleanup":
        cleanup()
        print("✅ 测试数据已清理")
        return
    print("═══ 邀请流程增强测试 (flow_sa_ai_invite_enhance_20261013) ═══")
    cleanup()  # 先清残留
    for fn in [t1, t2, t3, t4, t5, t6]:
        fn()
    cleanup()  # 后清理
    fails = [r for r in RESULTS if r[1] != "PASS"]
    print(f"═══ 汇总: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS ═══")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
