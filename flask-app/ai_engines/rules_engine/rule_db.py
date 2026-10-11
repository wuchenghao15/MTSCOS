"""
规则相关表的 DAO 操作
================================

维护 3 张规则治理表:
- mt_rule_changelog:       规则变更日志
- mt_rule_violation_alert: 违反告警投喂记录
- mt_rule_integrity_scan:  完整性自检报告

依赖 SQLite 主库 (与系统主 DB 同源, 避免新建连接池)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional


# Flask/演化权威库 (v23 修正: changelog 必须与 Flask/before_request/SA 页面读同一个库)
# 本文件位于 flask-app/ai_engines/rules_engine/, 上溯三级到 flask-app
_FLASK_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FLASK_DB = os.path.join(_FLASK_APP, "database", "app.db")

# 旧主库路径 (历史 mtscos.db, 仅在权威库缺失时回退)
_DB_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "_runtime",
        "databases",
        "Database",
        "mtscos.db",
    )
)

# 兼容回退 (历史路径 app.db / ai_engines/app.db)
_LEGACY_PATHS = [
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "_runtime", "databases", "Database", "app.db")
    ),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.db")),
]


def _resolve_db_path() -> str:
    """权威优先 flask-app/database/app.db (Flask/演化同库), 再回退 mtscos.db/legacy, 最后 :memory:

    历史教训: 旧版优先 _runtime/.../mtscos.db, 导致治理写入与 Flask 读取分叉到两个库。
    """
    if os.path.exists(_FLASK_DB):
        return _FLASK_DB
    if os.path.exists(_DB_PATH):
        return _DB_PATH
    for p in _LEGACY_PATHS:
        if os.path.exists(p):
            return p
    return ":memory:"

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS mt_rule_changelog (
        changelog_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id               TEXT NOT NULL,
        from_version          TEXT,
        to_version            TEXT,
        change_type           TEXT,
        change_summary        TEXT,
        approved_by_7step     INTEGER NOT NULL DEFAULT 0,
        sa_final_decision     TEXT,
        sa_vikey_verified     INTEGER NOT NULL DEFAULT 0,
        eigenflux_panel_json  TEXT,
        admin_approvers_json  TEXT,
        is_secret_withdrawn   INTEGER NOT NULL DEFAULT 0,
        created_at            TEXT,
        action                TEXT,
        target_table          TEXT,
        risk                  TEXT,
        pre_check_passed      INTEGER DEFAULT 0,
        execution_status      TEXT,
        execution_result      TEXT,
        execution_error       TEXT,
        executed_at           TEXT,
        pipeline_id           TEXT,
        CONSTRAINT uk_rule_version UNIQUE (rule_id, to_version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rule_changelog_rule_id ON mt_rule_changelog(rule_id)",
    "CREATE INDEX IF NOT EXISTS idx_rule_changelog_created ON mt_rule_changelog(created_at)",
    """
    CREATE TABLE IF NOT EXISTS mt_rule_violation_alert (
        alert_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        viol_id         TEXT,
        alert_type      TEXT,
        alert_target    TEXT,
        alert_status    TEXT,
        alert_payload   TEXT,
        alert_sent_at   TEXT,
        created_at      TEXT,
        violation_code  TEXT,
        severity        TEXT,
        description     TEXT,
        evidence        TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rva_violation_code ON mt_rule_violation_alert(violation_code)",
    "CREATE INDEX IF NOT EXISTS idx_rva_status ON mt_rule_violation_alert(alert_status)",
    "CREATE INDEX IF NOT EXISTS idx_rva_created ON mt_rule_violation_alert(created_at)",
    """
    CREATE TABLE IF NOT EXISTS mt_rule_integrity_scan (
        scan_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_type        TEXT,
        rule_id          TEXT,
        total_checks     INTEGER NOT NULL,
        passed           INTEGER NOT NULL,
        failed           INTEGER NOT NULL,
        score            REAL,
        gap_items        TEXT,
        recommendations  TEXT,
        triggered_by     TEXT,
        created_at       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ris_rule_id ON mt_rule_integrity_scan(rule_id)",
    "CREATE INDEX IF NOT EXISTS idx_ris_created ON mt_rule_integrity_scan(created_at)",
]


class RuleDB:
    """规则相关表的 DAO"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _resolve_db_path()
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        # 🔧 仙女座 v5.0: timeout=30s + WAL + checkpoint=10000
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 10000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _ensure_tables(self) -> None:
        # 每条 DDL 独立容错: 权威库为既有表, 个别索引列在历史 schema 上可能缺失,
        # 不应让一条 CREATE INDEX 失败中断其余治理表初始化。
        conn = self._get_conn()
        try:
            for ddl in _DDL_STATEMENTS:
                try:
                    conn.execute(ddl)
                except sqlite3.Error as exc:
                    print(f"[WARN] 规则表 DDL 跳过(既有库兼容): {str(exc)[:80]}")
            conn.commit()
        except sqlite3.Error as exc:
            print(f"[ERROR] 初始化规则表失败: {exc}")
        finally:
            conn.close()

    def insert_rule_changelog(
        self,
        rule_id: str,
        rule_file: str,
        from_version: str,
        to_version: str,
        change_type: str,
        change_summary: str,
        change_diff: str = "",
        approved_by_7step: int = 0,
        sa_final_decision: str = "",
        sa_vikey_verified: int = 0,
        proposer: str = "AI管理员",
        eigenflux_panel_json: str = "",
        admin_approvers_json: str = "",
        effective_at: Optional[str] = None,
        is_secret_withdrawn: int = 0,
    ) -> int:
        sql = """
            INSERT INTO mt_rule_changelog
                (rule_id, from_version, to_version, change_type, change_summary,
                 approved_by_7step, sa_final_decision, sa_vikey_verified,
                 eigenflux_panel_json, admin_approvers_json, is_secret_withdrawn, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # 权威表无 rule_file/change_diff/proposer/effective_at 列:
        # rule_file 作为出处追加到 summary 留痕; change_diff/proposer/effective_at 不入库 (签名保留兼容)。
        summary = change_summary or ""
        if rule_file:
            summary = (summary + f"\n[rule_file] {rule_file}").strip()
        params = (
            rule_id, from_version, to_version, change_type, summary,
            approved_by_7step, sa_final_decision or "", sa_vikey_verified,
            eigenflux_panel_json or "", admin_approvers_json or "",
            is_secret_withdrawn, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        try:
            with self._get_conn() as conn:
                # 应用层幂等去重 (权威表未必有 UNIQUE 约束)
                dup = conn.execute(
                    "SELECT 1 FROM mt_rule_changelog WHERE rule_id=? AND to_version=? LIMIT 1",
                    (rule_id, to_version)).fetchone()
                if dup:
                    print(f"[WARN] 重复 changelog 记录: {rule_id} {to_version}")
                    return 0
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.lastrowid or 0
        except sqlite3.IntegrityError:
            print(f"[WARN] 重复 changelog 记录: {rule_id} {to_version}")
            return 0

    def insert_violation_alert(
        self,
        rule_id: str,
        violation_code: str,
        violation_detail: str = "",
        triggered_by: str = "",
        eigenflux_fed: int = 0,
        brain_fed: int = 0,
        sa_notified: int = 0,
    ) -> int:
        sql = """
            INSERT INTO mt_rule_violation_alert
                (alert_id, viol_id, alert_type, alert_target, alert_status, alert_payload,
                 created_at, violation_code, severity, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # 权威表 alert_id 为 TEXT 主键, 必须显式生成 (漏给会插成 NULL 孤儿行)。
        now_dt = datetime.now()
        now_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        alert_id = "ALERT_%s_%s_%s" % (
            re.sub(r'[^A-Za-z0-9_]', '', str(rule_id))[:40] or "RULE",
            now_dt.strftime("%Y%m%d%H%M%S"), os.urandom(2).hex())
        # viol_id(NOT NULL)=规则码; alert_target=上下文对象;
        # 明细/投喂者/投喂标记打包进 alert_payload(JSON); violation_detail→description。
        payload = json.dumps({
            "rule_id": rule_id, "triggered_by": triggered_by,
            "eigenflux_fed": int(eigenflux_fed or 0), "brain_fed": int(brain_fed or 0),
            "sa_notified": int(sa_notified or 0),
        }, ensure_ascii=False)
        status = "SENT" if (sa_notified or eigenflux_fed or brain_fed) else "PENDING"
        severity = "HIGH" if sa_notified else "MEDIUM"
        target = (triggered_by or violation_detail or rule_id)[:200]
        params = (
            alert_id, rule_id, "RULE_VIOLATION", target, status, payload,
            now_ts, violation_code, severity, violation_detail or "",
        )
        try:
            with self._get_conn() as conn:
                conn.execute(sql, params)
                conn.commit()
                return alert_id
        except sqlite3.Error as exc:
            print(f"[ERROR] 写入违反告警失败: {exc}")
            return 0

    def mark_violation_alert_fed(
        self, alert_id: int, eigenflux_fed: int = 1, brain_fed: int = 0, sa_notified: int = 0
    ) -> None:
        # 权威表用 alert_status(PENDING/SENT) + alert_sent_at 表达投喂; 标记位并入 alert_payload。
        new_status = "SENT" if (sa_notified or eigenflux_fed or brain_fed) else "PENDING"
        sent_at = datetime.now().timestamp() if new_status == "SENT" else None
        payload = json.dumps({"eigenflux_fed": int(eigenflux_fed or 0),
                              "brain_fed": int(brain_fed or 0),
                              "sa_notified": int(sa_notified or 0)}, ensure_ascii=False)
        sql = """
            UPDATE mt_rule_violation_alert
            SET alert_status = ?, alert_sent_at = COALESCE(?, alert_sent_at), alert_payload = ?
            WHERE alert_id = ?
        """
        try:
            with self._get_conn() as conn:
                conn.execute(sql, (new_status, sent_at, payload, alert_id))
                conn.commit()
        except sqlite3.Error as exc:
            print(f"[ERROR] 更新告警投喂标记失败: {exc}")

    def insert_integrity_scan(
        self,
        total_rules: int,
        scanned_rules: int,
        passed_rules: int,
        failed_rules: int,
        weak_words_count: int,
        missing_meta_count: int,
        missing_trigger_count: int,
        scan_report_json: str,
        scan_status: str,
    ) -> int:
        # 权威表列名不同: total_rules→total_checks, passed_rules→passed, failed_rules→failed;
        # scanned/弱词/缺 META/缺触发块/报告/状态 打包进 gap_items(JSON)。
        score = round(passed_rules / total_rules, 4) if total_rules else 0.0
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scan_id = "SCAN_RULE_INTEGRITY_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        gap_items = json.dumps({
            "scanned_rules": scanned_rules,
            "weak_words_count": weak_words_count,
            "missing_meta_count": missing_meta_count,
            "missing_trigger_count": missing_trigger_count,
            "scan_status": scan_status,
            "scan_report": scan_report_json,
        }, ensure_ascii=False)
        sql = """
            INSERT INTO mt_rule_integrity_scan
                (scan_id, scan_type, rule_id, total_checks, passed, failed, score,
                 gap_items, recommendations, triggered_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            scan_id, "RULE_INTEGRITY", None, total_rules, passed_rules, failed_rules, score,
            gap_items, "", "rules_engine", now_ts,
        )
        try:
            with self._get_conn() as conn:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.lastrowid or 0
        except sqlite3.Error as exc:
            print(f"[ERROR] 写入完整性自检报告失败: {exc}")
            return 0

    def query_latest_changelog(self, rule_id: str) -> Optional[dict]:
        sql = """
            SELECT * FROM mt_rule_changelog
            WHERE rule_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            with self._get_conn() as conn:
                cur = conn.execute(sql, (rule_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except sqlite3.Error:
            return None


def init_tables(db_path: Optional[str] = None) -> RuleDB:
    """初始化3张规则治理表, 返回 RuleDB 实例"""
    return RuleDB(db_path=db_path)
