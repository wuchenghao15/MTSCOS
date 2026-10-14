"""
reconcile.py — 存量陈旧单处置 CLI
===================================
python -m engines.approval reconcile --dry-run        # 只出清单不改库
python -m engines.approval reconcile --apply --confirm  # 归档 23 release, 保留 2 孤儿单

规则 (已由 SA 拍板):
  1. 23 单 release (wuchenghao15, 2026-10-02 提交, 主体全缺或终态) → expired
  2. 2 单 demo 孤儿 (节点数=0) → 保留 pending, 输出 SA 清单
  3. 其余 pending 单 → 原样不动

apply 效果:
  - 每个 release 单: 未决节点 → skipped, 写 actions(actor=system:reconcile_20261012,
    detail 含判定依据), requests.status=expired
  - 2 孤儿单只打印不写库
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
# [unused] from pathlib import Path

from .db import get_conn, DB_PATH
from .state_machine import finalize_request


RECONCILE_ACTOR = 'system:reconcile_20261012'


def _load_release_subject(conn, subject_id: str) -> str:
    """查 mt_release_sessions 主体: missing / terminal / draft / 其他"""
    if not subject_id:
        return 'missing'
    row = conn.execute(
        "SELECT status FROM mt_release_sessions WHERE release_id=?",
        (subject_id,)).fetchone()
    if not row:
        return 'missing'
    st = (row['status'] or '').lower()
    if st in ('full', 'rolled_back'):
        return 'terminal'
    if st in ('draft', 'releasing', 'canary', 'pct10', 'pct50', 'pct100'):
        return 'active'
    return st


def _scan() -> dict:
    """返回 {release_expire: [...], orphan: [...], other_pending: [...]}"""
    result: dict = {'release_expire': [], 'orphan': [], 'other_pending': []}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, COUNT(n.id) AS node_count "
            "FROM mt_approval_requests r "
            "LEFT JOIN mt_approval_nodes n ON n.request_id=r.request_id "
            "WHERE r.status='pending' "
            "GROUP BY r.request_id "
            "ORDER BY r.created_at").fetchall()
        for r in rows:
            rid = r['request_id']
            category = (r['category'] or '').lower()
            node_count = r['node_count'] or 0
            subject_id = r['subject_id'] or ''

            if category == 'release':
                verdict = _load_release_subject(conn, subject_id)
                result['release_expire'].append({
                    'request_id': rid,
                    'category': category,
                    'initiator': r['initiator'],
                    'subject_id': subject_id,
                    'subject_state': verdict,
                    'reason': f'subject_{verdict}',
                    'node_count': node_count,
                    'risk_level': r['risk_level'],
                    'created_at': r['created_at'],
                })
            elif node_count == 0:
                result['orphan'].append({
                    'request_id': rid,
                    'category': category,
                    'initiator': r['initiator'],
                    'subject_id': subject_id,
                    'reason': 'zero_nodes',
                    'risk_level': r['risk_level'],
                    'created_at': r['created_at'],
                })
            else:
                result['other_pending'].append({
                    'request_id': rid, 'category': category,
                    'initiator': r['initiator'],
                    'subject_id': subject_id,
                    'node_count': node_count,
                    'risk_level': r['risk_level'],
                    'created_at': r['created_at'],
                })
    return result


def _print_report(scan: dict) -> None:
    print(f"\n{'='*60}")
    print(f"📋 审批单 reconcile 扫描报告  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"{'='*60}")
    print(f"\n🗑️  release expired 候选: {len(scan['release_expire'])} 单")
    print(f"{'─'*40}")
    for i, r in enumerate(scan['release_expire'], 1):
        print(f"  [{i:02d}] {r['request_id']}  {r['category']:12s} "
              f"init={r['initiator']:15s} subject={r['subject_state']:10s} "
              f"risk={r['risk_level']}  nodes={r['node_count']}")
        print(f"       subject_id={r['subject_id'][:30] or '(empty)'}  created_at={r['created_at']}")

    print(f"\n⚠️  orphan zero-node 孤儿单 (保留): {len(scan['orphan'])} 单")
    print(f"{'─'*40}")
    for i, r in enumerate(scan['orphan'], 1):
        print(f"  [{i:02d}] {r['request_id']}  {r['category']:15s} "
              f"init={r['initiator']:15s}  risk={r['risk_level']}")
        print(f"       subject_id={r['subject_id'][:30] or '(empty)'}  created_at={r['created_at']}")

    print(f"\n⏳  其他 pending 单 (不动): {len(scan['other_pending'])} 单")
    print(f"{'─'*40}")
    for r in scan['other_pending'][:20]:
        print(f"  {r['request_id']}  {r['category']:15s} "
              f"init={r['initiator']:15s}  risk={r['risk_level']}  nodes={r['node_count']}")
    if len(scan['other_pending']) > 20:
        print(f"  ... 还有 {len(scan['other_pending']) - 20} 单省略")

    print(f"\n📦 DB 路径: {DB_PATH}")
    print(f"🔧 apply 时 actor={RECONCILE_ACTOR}")


def _apply(scan: dict) -> dict:
    summary = {'expired': 0, 'failed': 0, 'orphan_kept': len(scan['orphan'])}
    for r in scan['release_expire']:
        rid = r['request_id']
        reason = r['reason']
        try:
            res = finalize_request(rid, 'expired', RECONCILE_ACTOR, reason)
            if res.get('ok'):
                summary['expired'] += 1
                print(f"  ✅ expired  {rid}  ({reason})")
            else:
                summary['failed'] += 1
                print(f"  ❌ failed  {rid}  {res.get('msg')}")
        except Exception as e:
            summary['failed'] += 1
            print(f"  💥 crash   {rid}  {e}")
    print(f"\n📊 结果: expired={summary['expired']}  failed={summary['failed']}  "
          f"orphan_kept={summary['orphan_kept']}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='审批陈旧单 reconcile')
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true', help='只出清单不改库')
    group.add_argument('--apply', action='store_true', help='归档 release expired 单')
    ap.add_argument('--confirm', action='store_true', help='--apply 必须带 --confirm')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    args = ap.parse_args(argv)

    scan = _scan()

    if args.json:
        print(json.dumps(scan, ensure_ascii=False, indent=2))
        return 0

    _print_report(scan)

    if args.dry_run:
        return 0

    if args.apply:
        if not args.confirm:
            print("\n❌ --apply 必须带 --confirm 才执行")
            return 2
        print(f"\n⚠️  即将归档 {len(scan['release_expire'])} 单 release expired, "
              f"保留 {len(scan['orphan'])} 单 orphan.")
        print("🚀 执行中 ...\n")
        summary = _apply(scan)
        if summary['failed']:
            return 1
        return 0

    return 0


if __name__ == '__main__':
    sys.exit(main())
