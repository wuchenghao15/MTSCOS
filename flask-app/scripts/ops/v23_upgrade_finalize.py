#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v23.0.0 MAJOR 升级 —— SA VIKEY 终审落定脚本（待命，默认 dry-run）
====================================================================

仅超级管理员 wuchenghao15 在本机插入已绑定的 SA VIKEY 硬件狗、并持有实时
认证会话时才能执行。脚本做四件事：
  1. fail-closed 实时校验 SA VIKEY：在线 + 绑定 super_admin + 已认证会话；
  2. 校验 EigenFlux 磋商记录 ≥4/5 PASS（取自 mt_rule_changelog 草稿）；
  3. 落定 flask-app/VERSION 为 v23.0.0（V-05 唯一权威，先备份）；
  4. 回写治理三字段 approved_by_7step=1 / sa_final_decision / sa_vikey_verified=1。

设计约束：
  - 默认 **dry-run**，只检查与打印，不写任何东西；真正落定必须显式 --execute；
  - 不自动 git commit/tag/push（SA 专属），只打印待执行命令；
  - 不自动 launchctl（SA 专属）；不写 system_versions（VERSION 即权威，DB 不改版本号）；
  - 不降级（V-06）；驳回(decision=驳回)只记录裁决，绝不 bump VERSION。

用法（在 flask-app 目录、SA 狗已插入且已通过双钥登录）：
  python3 scripts/ops/v23_upgrade_finalize.py                 # 预检 dry-run
  python3 scripts/ops/v23_upgrade_finalize.py --execute                    # 立即适配
  python3 scripts/ops/v23_upgrade_finalize.py --execute --decision 驳回
  python3 scripts/ops/v23_upgrade_finalize.py --execute --token <1800s 会话token>
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

FLASK = Path(__file__).resolve().parents[2]          # scripts/ops/ → flask-app/
sys.path.insert(0, str(FLASK))

VERSION_FILE = FLASK / "VERSION"
DB_PATH = FLASK / "database" / "app.db"

RULE_ID = "SYSTEM_VERSION"
FROM_TAG = "v22.2.0"
TO_CORE = "23.0.0"
TO_TAG = "v" + TO_CORE
SA_USERNAME = "wuchenghao15"
DECISIONS = ("立即适配", "2个工作日后", "驳回")


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def info(m: str) -> None: print(f"[INFO] {m}")
def ok(m: str) -> None: print(f"[✅] {m}")
def warn(m: str) -> None: print(f"[⚠️ ] {m}")
def err(m: str) -> None: print(f"[❌] {m}", file=sys.stderr)


def load_draft(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """SELECT changelog_id, from_version, to_version, change_type,
                  approved_by_7step, sa_final_decision, sa_vikey_verified,
                  eigenflux_panel_json, execution_status
             FROM mt_rule_changelog
            WHERE rule_id=? AND to_version=? LIMIT 1""",
        (RULE_ID, TO_TAG),
    ).fetchone()
    if not row:
        return None
    keys = ["changelog_id", "from_version", "to_version", "change_type",
            "approved_by_7step", "sa_final_decision", "sa_vikey_verified",
            "eigenflux_panel_json", "execution_status"]
    return dict(zip(keys, row))


def panel_gate(draft: dict) -> tuple[bool, str, dict]:
    """EigenFlux ≥4/5 PASS 才放行终审。返回 (pass, reason, panel)。"""
    try:
        panel = json.loads(draft.get("eigenflux_panel_json") or "{}")
    except Exception as e:
        return False, f"磋商记录 JSON 解析失败: {e}", {}
    votes = panel.get("votes") or []
    pass_n = int(panel.get("pass_count") or 0)
    if len(votes) < 5:
        return False, f"磋商席位不足: {len(votes)}/5", panel
    if pass_n < 4:
        return False, f"EigenFlux 仅 {pass_n}/5 PASS，未达 4/5 阈值", panel
    return True, f"EigenFlux {pass_n}/5 PASS", panel


def verify_sa_vikey(token: str | None = None) -> tuple[bool, str, dict]:
    """实时 SA VIKEY 校验 (fail-closed)。返回 (ok, reason, evidence)。"""
    evidence: dict = {"checked_at": _ts()}
    try:
        from core.services.vikey_api import get_vikey_api
    except Exception as e:
        return False, f"vikey_api 不可用: {str(e)[:120]}", evidence
    try:
        api = get_vikey_api()
        det = api.detect()
        evidence["has_super_admin_key"] = bool(det.get("has_super_admin_key"))
        serial = det.get("super_admin_serial")
        evidence["super_admin_serial"] = serial
        evidence["super_admin_username"] = det.get("super_admin_username")
        if not det.get("has_super_admin_key") or not serial:
            return False, "未检测到在线的 SA 超级管理员绑定 VIKEY", evidence
        if (det.get("super_admin_username") or "").strip().lower() != SA_USERNAME:
            return False, f"在线 SA 狗用户名非 {SA_USERNAME}: {det.get('super_admin_username')}", evidence
        if not api.is_present(serial):
            return False, f"VIKEY {serial} 非实时在线 (is_present=False)", evidence

        binding = api.get_binding(serial) or {}
        evidence["binding_status"] = binding.get("binding_status")
        evidence["role_hint"] = binding.get("role_hint") or binding.get("role")
        if str(binding.get("binding_status") or "").lower() != "bound":
            return False, "SA VIKEY 绑定状态非 bound", evidence
        if str(evidence["role_hint"] or "").lower() not in ("super_admin", "hardware_vikey_admin"):
            return False, f"SA VIKEY 角色不符: {evidence['role_hint']}", evidence

        # 实时认证会话：狗本身已登录，或传入有效会话 token
        if api.is_logged_in(serial):
            evidence["session"] = "live_logged_in"
            return True, "SA VIKEY 在线且已认证 (live session)", evidence
        if token and api.ensure_session(token, serial):
            evidence["session"] = "token_ensured"
            return True, "SA VIKEY 在线且会话 token 有效", evidence
        return False, "SA VIKEY 在线但无实时认证会话 (请先双钥登录或传 --token)", evidence
    except Exception as e:
        return False, f"VIKEY 实时校验异常: {str(e)[:150]}", evidence


def read_version_raw() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def do_execute(decision: str, token: str | None) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        draft = load_draft(conn)
        if not draft:
            err(f"未找到 {RULE_ID} {TO_TAG} 治理草稿，拒绝终审")
            return 2
        if int(draft["approved_by_7step"] or 0) == 1:
            err("该草稿已终审 (approved_by_7step=1)，拒绝重复执行")
            return 3

        gate_ok, gate_msg, _ = panel_gate(draft)
        if not gate_ok:
            err("EigenFlux 磋商未过门: " + gate_msg)
            return 4
        info(gate_msg)

        vk_ok, vk_msg, evidence = verify_sa_vikey(token)
        if not vk_ok:
            err("SA VIKEY 校验失败 (fail-closed): " + vk_msg)
            return 5
        ok(vk_msg)

        now = _ts()
        if decision == "驳回":
            conn.execute(
                """UPDATE mt_rule_changelog
                      SET approved_by_7step=1, sa_final_decision=?, sa_vikey_verified=1,
                          execution_status='REJECTED', execution_result=?, executed_at=?
                    WHERE changelog_id=?""",
                (decision, f"SA 驳回; VIKEY 证据={json.dumps(evidence, ensure_ascii=False)}",
                 now, draft["changelog_id"]),
            )
            conn.commit()
            warn("已记录 SA 驳回，VERSION 未改动，不升级")
            return 0

        if decision == "2个工作日后":
            conn.execute(
                """UPDATE mt_rule_changelog
                      SET approved_by_7step=1, sa_final_decision=?, sa_vikey_verified=1,
                          execution_status='DEFERRED_2WORKDAYS', execution_result=?, executed_at=?
                    WHERE changelog_id=?""",
                (decision, f"SA 裁决 2 个工作日后适配; VERSION 暂不改; VIKEY={json.dumps(evidence, ensure_ascii=False)}",
                 now, draft["changelog_id"]),
            )
            conn.commit()
            warn("已记录 SA '2个工作日后'，VERSION 暂不 bump")
            return 0

        # decision == 立即适配 → 真正落定版本
        cur = read_version_raw()
        if cur == TO_TAG:
            warn(f"VERSION 已是 {TO_TAG}，跳过写文件")
        else:
            if cur != FROM_TAG:
                err(f"当前 VERSION={cur!r} 与预期 {FROM_TAG} 不符，拒绝覆盖（防止误升/跨版本）")
                return 6
            backup = VERSION_FILE.with_name(f"VERSION.bak.{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
            backup.write_text(cur + "\n", encoding="utf-8")
            VERSION_FILE.write_text(TO_TAG + "\n", encoding="utf-8")
            ok(f"VERSION {FROM_TAG} → {TO_TAG}（备份 {backup.name}）")

        # 回读 SSOT 校验
        try:
            from core import version_source as vs
            assert vs.get_system_version_tagged() == TO_TAG, "SSOT 回读不等于目标版本"
            ok(f"SSOT 回读通过: {vs.get_system_version_tagged()}")
        except Exception as e:
            err(f"SSOT 回读失败，请人工核查 VERSION: {e}")
            return 7

        conn.execute(
            """UPDATE mt_rule_changelog
                  SET approved_by_7step=1, sa_final_decision=?, sa_vikey_verified=1,
                      execution_status='DONE', execution_result=?, executed_at=?
                WHERE changelog_id=?""",
            (decision,
             f"VERSION 落定 {TO_TAG}; EigenFlux 5人磋商过 4/5 门; VIKEY 证据={json.dumps(evidence, ensure_ascii=False)}; "
             f"DB 不改版本号(V-05); launchctl/git tag/push 由 SA 另行执行",
             now, draft["changelog_id"]),
        )
        conn.commit()
        ok(f"治理三字段已回写 (changelog_id={draft['changelog_id']})")

        print()
        info("后续 SA 手动步骤（脚本不自动执行）：")
        print("  1) git add flask-app/VERSION && git commit -m 'release: v23.0.0 (SA VIKEY finalized)'")
        print(f"  2) git tag -a {TO_TAG} -m 'MTSCOS iceberg {TO_TAG}' && git push origin main --tags")
        print("  3) launchctl 重新拉起 smart_mount 主管 / 重启 8888 服务（SA 域）")
        print("  4) Mac mini 升同版本前，tri_sync 跨 major DB 默认阻断；mini 就绪后再同步（或迁移窗口 MTSCOS_ALLOW_MAJOR_SYNC=1）")
        return 0
    finally:
        conn.close()


def do_dry_run() -> int:
    info("=== v23.0.0 终审预检 (dry-run, 不写任何内容) ===")
    info(f"VERSION 文件: {VERSION_FILE} -> 当前 {read_version_raw() or '(不可读)'} (目标 {TO_TAG})")
    conn = sqlite3.connect(DB_PATH)
    try:
        draft = load_draft(conn)
        if not draft:
            err(f"缺少 {RULE_ID} {TO_TAG} 治理草稿")
            return 2
        info(f"草稿 changelog_id={draft['changelog_id']} type={draft['change_type']} "
             f"approved7={draft['approved_by_7step']} status={draft['execution_status']}")
        gate_ok, gate_msg, _ = panel_gate(draft)
        (ok if gate_ok else warn)(gate_msg)
    finally:
        conn.close()
    vk_ok, vk_msg, ev = verify_sa_vikey(None)
    (ok if vk_ok else warn)("SA VIKEY: " + vk_msg + f"  evidence={json.dumps(ev, ensure_ascii=False)}")
    print()
    info("预检完成。真正落定请在 SA 狗在线+已认证时运行：")
    print("  python3 scripts/ops/v23_upgrade_finalize.py --execute")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="v23.0.0 SA VIKEY 终审脚本（默认 dry-run）")
    ap.add_argument("--execute", action="store_true", help="真正执行终审落定（默认仅预检）")
    ap.add_argument("--decision", default="立即适配", choices=DECISIONS, help="SA 终审裁决")
    ap.add_argument("--token", default=os.environ.get("MTSCOS_VIKEY_TOKEN", ""), help="VIKEY 实时会话 token（或 env MTSCOS_VIKEY_TOKEN）")
    args = ap.parse_args()
    if not args.execute:
        return do_dry_run()
    if args.decision not in DECISIONS:
        err(f"非法裁决: {args.decision}")
        return 8
    return do_execute(args.decision, args.token or None)


if __name__ == "__main__":
    raise SystemExit(main())
