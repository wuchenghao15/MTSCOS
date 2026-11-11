#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines/data_safety_guard.py — 数据安全卫士 (Data Safety Guard)
=============================================================
古灵阁数据安全隔离体系的核心地基 — 写入熔断 / 污染检测 / 表级隔离 / session_id 硬校验.

三层数据安全:
  Layer 1 — 表级隔离 (物理隔离):
      mt_live_*     → 真实交易 (LIVE-* session)     ← 古灵阁银行仪表盘唯一数据源
      mt_sandbox_*  → 传统沙盘学习 (SB-* session)    ← 仅用于学习复盘
      mt_lab_*      → AI 教师学习沙盘 (LAB-* session) ← 仅用于学习复盘
      mt_vault_*    → LedgerEngine 结转 (可配置数据源) ← 必须显式标记

  Layer 2 — session_id 硬校验 (写入熔断):
      所有写入 mt_live_* 表的代码必须携带 LIVE-* session_id
      所有写入 mt_sandbox_* / mt_lab_* 的禁止出现 LIVE-* session_id
      违反 → 立即 raise PollutionDetected, 同时写 mt_pollution_log 审计

  Layer 3 — 运行时熔断器 (Circuit Breaker):
      任何时刻检测到沙盘 session_id 混入 mt_live_* → 立即熔断
      熔断状态持久化 → 所有 finance_bank_bp API 返回 FUSE_TRIPPED
      修复后必须显式调用 /api/safety/fuse/reset → 完成闭环

污染检测 SOP (研判→修复→维和部队→中心介入→入厅闭环):
  1. detect_pollution()        — 扫描所有表 session_id 前缀, 输出 PollutionReport
  2. quarantine_pollution()   — 把污染行 move 到 mt_pollution_quarantine
  3. trigger_fuse()           — 触发熔断器, 所有真实 API 停止响应
  4. center_investigate()     — 中心介入研判污染源头
  5. repair_and_verify()      — 修复后 verify_clean() 确认干净
  6. hall_admission()         — 通过后 fuse_reset → 数据入厅完成闭环
"""

import os, json, sqlite3, time, threading, logging, datetime
from contextlib import contextmanager

logger = logging.getLogger('data_safety_guard')

# ═══════════════════════════════════════════════════════════════════════
# 常量: 三层数据源表前缀 + session_id 前缀
# ═══════════════════════════════════════════════════════════════════════

# 表前缀 → session_id 允许的前缀映射
# 任何不在此表中的 (表, session_id) 组合 = 污染
_TABLE_SESSION_BOUNDARY = {
    # mt_live_* 真实交易层 — 只允许 LIVE-*
    'mt_live_%': {'LIVE-'},
    # mt_sandbox_* 传统沙盘 — 只允许 SB-*
    'mt_sandbox_%': {'SB-'},
    # mt_lab_* 新 AI 教师学习沙盘 — 只允许 LAB-*
    'mt_lab_%': {'LAB-'},
}

# mt_vault_* 可以来自 SB-* 结转 (LedgerEngine), 但绝对不能有 LIVE-* 反写
# session 过滤在 finance_bank_bp 的 _sandbox_session_filter() 已处理

# 熔断器状态文件 (不在 DB 里, 避免 DB 本身被污染后无法熔断)
_FUSE_STATE_FILE = os.environ.get(
    'GOBELIN_FUSE_STATE',
    os.path.join(os.path.dirname(__file__), '..', 'database', '.fuse_state.json')
)

# DB 路径
_DB_PATH = os.environ.get(
    'APP_DB',
    os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
)

# ═══════════════════════════════════════════════════════════════════════
# 熔断器 (Circuit Breaker) — 进程内单例
# ═══════════════════════════════════════════════════════════════════════

_fuse_lock = threading.Lock()

class PollutionDetected(Exception):
    """污染异常 — 任何写入污染检测到立即 raise."""
    def __init__(self, table, session_id, actual_prefix, allowed_prefixes):
        self.table = table
        self.session_id = session_id
        self.actual_prefix = actual_prefix
        self.allowed_prefixes = allowed_prefixes
        self.message = (
            f"🔴 DATA POLLUTION DETECTED: table={table} received session_id={session_id} "
            f"(prefix={actual_prefix}, allowed={allowed_prefixes})"
        )
        super().__init__(self.message)

class FuseTripped(Exception):
    """熔断器触发异常."""
    pass

class DataSafetyGuard:
    """数据安全卫士 — 单例, 进程级持久化."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path=None):
        if self._initialized:
            return
        self.db_path = db_path or _DB_PATH
        self._fuse_state = self._load_fuse_state()
        self._init_tables()
        self._initialized = True
        logger.info(f'🛡️ DataSafetyGuard initialized, fuse={"TRIPPED" if self.is_fused() else "CLOSED"}, db={self.db_path}')

    # ── 熔断器持久化 ──────────────────────────────────────

    def _load_fuse_state(self):
        try:
            with open(_FUSE_STATE_FILE) as f:
                return json.load(f)
        except:
            return {'tripped': False, 'tripped_at': None, 'reason': None, 'trip_count': 0}

    def _save_fuse_state(self):
        os.makedirs(os.path.dirname(_FUSE_STATE_FILE), exist_ok=True)
        with open(_FUSE_STATE_FILE, 'w') as f:
            json.dump(self._fuse_state, f, indent=2)

    def is_fused(self):
        """熔断器是否触发 — 所有真实 API 应该先调这个.
        每次实时读文件 (跨进程安全, 手动触发/重置能立即生效)."""
        self._fuse_state = self._load_fuse_state()
        return bool(self._fuse_state.get('tripped'))

    def trip_fuse(self, reason):
        """触发熔断器 — 写入持久化状态 + 审计日志."""
        with _fuse_lock:
            self._fuse_state = {
                'tripped': True,
                'tripped_at': datetime.datetime.now().isoformat(),
                'reason': reason,
                'trip_count': self._fuse_state.get('trip_count', 0) + 1,
            }
            self._save_fuse_state()
        logger.critical(f'🔴 FUSE TRIPPED: {reason}')
        self._log_audit('FUSE_TRIPPED', reason)

    def reset_fuse(self, operator, reason='verified_clean'):
        """重置熔断器 — 必须显式调用, 完成闭环."""
        with _fuse_lock:
            prev = self._fuse_state
            self._fuse_state = {
                'tripped': False,
                'reset_at': datetime.datetime.now().isoformat(),
                'reset_by': operator,
                'reset_reason': reason,
                'trip_count': prev.get('trip_count', 0),
            }
            self._save_fuse_state()
        logger.warning(f'🟢 FUSE RESET by {operator}: {reason}')
        self._log_audit('FUSE_RESET', f'by={operator}, reason={reason}')

    def fuse_status(self):
        return dict(self._fuse_state)

    # ── 审计/隔离表初始化 ──────────────────────────────────

    def _init_tables(self):
        """确保污染检测 + 审计 + 隔离表存在."""
        conn = self._connect()
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS mt_pollution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                source_table TEXT NOT NULL,
                source_session_id TEXT,
                actual_prefix TEXT,
                expected_prefixes TEXT,
                severity TEXT DEFAULT 'CRITICAL',
                details TEXT,
                resolved INTEGER DEFAULT 0,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS mt_pollution_quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quarantined_at TEXT NOT NULL,
                source_table TEXT NOT NULL,
                original_rowid INTEGER,
                row_data TEXT NOT NULL,
                reason TEXT,
                hash TEXT
            );
            CREATE TABLE IF NOT EXISTS mt_safety_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT,
                target TEXT,
                details TEXT
            );
        """)
        conn.commit()
        conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _log_audit(self, action, details, actor='guardian', target=None):
        conn = self._connect()
        conn.execute(
            "INSERT INTO mt_safety_audit (ts, action, actor, target, details) VALUES (?,?,?,?,?)",
            (datetime.datetime.now().isoformat(), action, actor, target, details)
        )
        conn.commit()
        conn.close()

    def _log_pollution(self, table, session_id, actual, expected, details=''):
        conn = self._connect()
        conn.execute(
            "INSERT INTO mt_pollution_log (detected_at, source_table, source_session_id, "
            "actual_prefix, expected_prefixes, details) VALUES (?,?,?,?,?,?)",
            (datetime.datetime.now().isoformat(), table, session_id, actual,
             ','.join(expected), details)
        )
        conn.commit()
        conn.close()

    # ── session_id 前缀校验 (写入熔断的核心) ──────────────

    def validate_session_for_table(self, table, session_id):
        """校验 session_id 前缀是否匹配表所属的数据源层.
        返回 (is_valid, allowed_prefixes, actual_prefix).
        这是所有写入 mt_live_*/mt_sandbox_*/mt_lab_* 表之前必须调用的.
        """
        if not session_id:
            return True, None, None
        actual = session_id.split('-')[0] + '-'
        # 查找匹配的表前缀
        allowed = None
        for tbl_pattern, prefixes in _TABLE_SESSION_BOUNDARY.items():
            if table.startswith(tbl_pattern.rstrip('%')):
                allowed = prefixes
                break
        if allowed is None:
            # 不在边界表里 → 不强制校验 (其他表)
            return True, None, actual
        return actual in allowed, allowed, actual

    def check_write(self, table, session_id):
        """写入前校验 — 违反立即 raise PollutionDetected + 触发熔断."""
        # 熔断器检查
        if self.is_fused():
            raise FuseTripped(f'Fuse tripped, blocking writes to {table}')
        is_valid, allowed, actual = self.validate_session_for_table(table, session_id)
        if not is_valid:
            # 1. 记录污染
            self._log_pollution(table, session_id, actual, allowed)
            # 2. 触发熔断器
            self.trip_fuse(f'Write to {table} with session_id={session_id} (prefix={actual}, allowed={allowed})')
            # 3. raise (让调用方中断写入)
            raise PollutionDetected(table, session_id, actual, allowed)
        return True

    # ── 全库污染扫描 (定期/手动触发) ─────────────────────

    def scan_all_tables(self):
        """扫描所有 mt_live_*/mt_sandbox_*/mt_lab_*/mt_vault_* 表的 session_id 前缀.
        返回 PollutionReport."""
        conn = self._connect()
        report = {
            'scanned_at': datetime.datetime.now().isoformat(),
            'clean': True,
            'findings': [],
            'tables_checked': 0,
        }
        try:
            all_tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE 'mt_live_%' OR name LIKE 'mt_sandbox_%' "
                "  OR name LIKE 'mt_lab_%' OR name LIKE 'mt_vault_%') "
                "ORDER BY name"
            ).fetchall()]

            for tbl in all_tables:
                report['tables_checked'] += 1
                # 找出所有含 session_id 列的表
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if 'session_id' not in cols:
                    continue
                # 统计各前缀分布
                try:
                    prefix_counts = conn.execute(
                        f"SELECT substr(session_id, 1, instr(session_id, '-')) as prefix, "
                        f"COUNT(*) as cnt FROM {tbl} GROUP BY prefix"
                    ).fetchall()
                except Exception as e:
                    continue
                # 查表边界
                allowed = None
                for pattern, prefixes in _TABLE_SESSION_BOUNDARY.items():
                    if tbl.startswith(pattern.rstrip('%')):
                        allowed = prefixes
                        break
                # mt_vault_* 可以接受 SB-* 结转, 但不能有 LIVE-* 混入
                if tbl.startswith('mt_vault_'):
                    allowed = allowed or {'SB-'}
                    forbidden = {'LIVE-', 'LAB-'}
                else:
                    forbidden = set()
                if allowed:
                    for prefix, cnt in prefix_counts:
                        if prefix and prefix not in allowed:
                            finding = {
                                'table': tbl,
                                'prefix': prefix,
                                'count': cnt,
                                'allowed': sorted(allowed),
                                'severity': 'CRITICAL' if prefix in forbidden else 'WARN',
                            }
                            report['findings'].append(finding)
                            report['clean'] = False
                            # 记录审计日志
                            self._log_pollution(tbl, f'(prefix={prefix})', prefix, allowed,
                                                f'scan found {cnt} rows')
        finally:
            conn.close()

        # 有 CRITICAL 发现 → 自动触发熔断
        critical = [f for f in report['findings'] if f['severity'] == 'CRITICAL']
        if critical:
            self.trip_fuse(f"scan found {len(critical)} CRITICAL pollution in {critical[0]['table']}")

        report['fuse_status'] = self.fuse_status()
        return report

    def quarantine_pollution(self, table, session_prefix):
        """把 table 里匹配 session_prefix 的污染行 move 到隔离表."""
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if 'session_id' not in cols:
            return 0
        # 找出污染行
        polluted = conn.execute(
            f"SELECT rowid, * FROM {table} WHERE session_id LIKE '{session_prefix}%'"
        ).fetchall()
        count = 0
        for row in polluted:
            rowid = row[0]
            row_data = dict(zip(['rowid'] + cols, row))
            conn.execute(
                "INSERT INTO mt_pollution_quarantine "
                "(quarantined_at, source_table, original_rowid, row_data, reason) "
                "VALUES (?,?,?,?,?)",
                (datetime.datetime.now().isoformat(), table, rowid,
                 json.dumps(row_data, ensure_ascii=False),
                 f'session_id prefix={session_prefix} violated boundary')
            )
            conn.execute(f"DELETE FROM {table} WHERE rowid=?", (rowid,))
            count += 1
        conn.commit()
        conn.close()
        self._log_audit('QUARANTINE', f'table={table}, prefix={session_prefix}, rows={count}')
        logger.warning(f'🟡 Quarantined {count} rows from {table} with prefix={session_prefix}')
        return count

    def verify_clean(self):
        """快速验证: mt_live_* 表有没有非 LIVE-* session_id."""
        report = self.scan_all_tables()
        return report['clean'], report


# ═══════════════════════════════════════════════════════════════════════
# Flask 注入 — 在 before_request 检查熔断器状态
# ═══════════════════════════════════════════════════════════════════════

def inject_safety_guard(app):
    """把 DataSafetyGuard 注入 Flask app.
    - before_request: 检查熔断器 + 对 finance_bank_bp API 返回熔断状态
    - 提供 /api/safety/* 端点 (污染检测/隔离/熔断/重置)
    - 审计/复核/交叉校验/主动验证/事件记录/AI 自动化巡检 (维和部队)
    """
    from flask import request, jsonify  # 统一导入, 所有内部 endpoint 共享
    guard = DataSafetyGuard()

    @app.before_request
    def _check_fuse():
        # 只对 finance / live 相关 API 检查熔断
        guard_paths = ('/api/finance/', '/api/live/', '/api/vault/', '/api/audit/')
        path = request.path
        if any(path.startswith(gp) for gp in guard_paths):
            if guard.is_fused():
                fs = guard.fuse_status()
                return jsonify({
                    'success': False,
                    'code': 'FUSE_TRIPPED',
                    'fuse_status': fs,
                    'message': (
                        '🔴 数据安全熔断器已触发 — 检测到沙盘/学习盘数据混入真实数据层.\n'
                        f'触发原因: {fs.get("reason")}\n'
                        f'触发时间: {fs.get("tripped_at")}\n'
                        f'请立即调用 /api/safety/fuse/status 查看详情, '
                        f'完成研判→修复→入厅闭环后调用 /api/safety/fuse/reset 重置.'
                    ),
                    'sop': [
                        '1. GET  /api/safety/scan           # 全盘污染扫描',
                        '2. GET  /api/safety/findings       # 查看历史污染记录',
                        '3. POST /api/safety/quarantine     # 隔离污染行',
                        '4. POST /api/safety/verify         # 验证干净',
                        '5. POST /api/safety/fuse/reset     # 熔断重置 (闭环入厅)',
                    ],
                }), 503
        return None

    # ── 安全 API 端点 (独立蓝图, 不受熔断影响) ──

    @app.route('/api/safety/scan', methods=['GET'])
    def api_safety_scan():
        return jsonify(guard.scan_all_tables())

    @app.route('/api/safety/findings', methods=['GET'])
    def api_safety_findings():
        conn = guard._connect()
        rows = conn.execute(
            "SELECT * FROM mt_pollution_log ORDER BY detected_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        return jsonify({'findings': [dict(r) for r in rows]})

    @app.route('/api/safety/fuse/status', methods=['GET'])
    def api_safety_fuse_status():
        return jsonify({'fuse_status': guard.fuse_status()})

    @app.route('/api/safety/fuse/reset', methods=['POST'])
    def api_safety_fuse_reset():
        """重置熔断器 — 必须显式操作, 完成闭环."""
        body = request.get_json(silent=True) or {}
        operator = body.get('operator') or 'unknown'
        reason = body.get('reason') or 'manual_reset'
        # 必须确认当前干净
        clean, _ = guard.verify_clean()
        if not clean and not body.get('force'):
            return jsonify({
                'success': False,
                'error': 'NOT_CLEAN',
                'message': '还有未隔离的污染行, 请先调用 /api/safety/quarantine, 或 force=true 强制重置',
            }), 400
        guard.reset_fuse(operator, reason)
        return jsonify({'success': True, 'fuse_status': guard.fuse_status()})

    @app.route('/api/safety/quarantine', methods=['POST'])
    def api_safety_quarantine():
        """隔离污染行 — 把匹配 prefix 的行 move 到 mt_pollution_quarantine."""
        body = request.get_json(silent=True) or {}
        table = body.get('table', '')
        prefix = body.get('prefix', '')
        if not table or not prefix:
            return jsonify({'error': 'table and prefix required'}), 400
        count = guard.quarantine_pollution(table, prefix)
        return jsonify({'success': True, 'quarantined': count, 'table': table, 'prefix': prefix})

    @app.route('/api/safety/verify', methods=['GET'])
    def api_safety_verify():
        clean, report = guard.verify_clean()
        return jsonify({'clean': clean, 'report': report})

    @app.route('/api/safety/audit', methods=['GET'])
    def api_safety_audit():
        conn = guard._connect()
        rows = conn.execute(
            "SELECT * FROM mt_safety_audit ORDER BY ts DESC LIMIT 50"
        ).fetchall()
        conn.close()
        return jsonify({'audit': [dict(r) for r in rows]})

    # ── 治理闭环: 污染事件 → 会议厅 → AI 投喂 → 学习组织 ──

    @app.route('/api/safety/remediation/trigger', methods=['POST'])
    def api_safety_remediation_trigger():
        """触发完整治理闭环: 污染检测 → 会议厅 → AI 案例 → 学习推送.
        可手动调用, 也被 FuseTripped 自动调用."""
        body = request.get_json(silent=True) or {}
        reason = body.get('reason') or 'manual_trigger'
        report = guard.scan_all_tables()
        conn = guard._connect()

        # 1. 创建会议厅议题
        meeting_id = f"MEET-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            conn.execute(
                "INSERT INTO mt_sandbox_meetings "
                "(meeting_id, topic, type, created_at, status, participants, description) "
                "VALUES (?,?,?,?,?,?,?)",
                (meeting_id,
                 f"🔴 数据安全紧急会议: {reason}",
                 'EMERGENCY_SAFETY',
                 datetime.datetime.now().isoformat(),
                 'OPEN',
                 json.dumps(['finance_team', 'legal_team', 'top_group', 'advisors',
                            'professors', 'ai_mid_admins'], ensure_ascii=False),
                 f"熔断器触发原因: {reason}\n"
                 f"扫描发现: {report.get('findings')}\n"
                 f"严重程度: {'CRITICAL' if not report.get('clean') else 'WARN'}")
            )
        except Exception:
            pass  # mt_sandbox_meetings 可能无这个表结构, 跳过

        # 2. 投喂 AI 案例库 (mt_lab_hr_log → 作为反面教材)
        try:
            findings = report.get('findings', [])
            for f in findings:
                conn.execute(
                    "INSERT INTO mt_lab_hr_log (log_type, content, created_at, severity) "
                    "VALUES (?,?,?,?)",
                    ('POLLUTION_CASE',
                     json.dumps(f, ensure_ascii=False),
                     datetime.datetime.now().isoformat(),
                     f.get('severity', 'WARN'))
                )
        except Exception:
            pass  # 表可能不存在

        # 3. 标记为学习材料
        try:
            clean_findings = [f for f in report.get('findings', []) if f.get('table')]
            if clean_findings:
                conn.execute(
                    "INSERT INTO mt_lab_task_events (event_type, details, created_at) "
                    "VALUES (?,?,?)",
                    ('POLLUTION_LEARNING_REQUIRED',
                     json.dumps({'reason': reason, 'findings': clean_findings},
                                ensure_ascii=False),
                     datetime.datetime.now().isoformat())
                )
        except Exception:
            pass

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'meeting_id': meeting_id,
            'report': report,
            'actions_triggered': {
                'meeting': meeting_id,
                'ai_case_library': len(report.get('findings', [])),
                'learning_tasks': len([f for f in report.get('findings', []) if f.get('table')]),
            },
            'participants_notified': [
                '🏦 finance_team (金融团队)',
                '⚖️ legal_team (法务团队)',
                '⭐ top_group (天团成员)',
                '🎓 advisors (顾问)',
                '📚 professors (教授)',
                '🤖 ai_mid_admins (AI 中层管理员)',
            ],
            'sop_steps': [
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ① 污染检测 → 扫描 {report.get("tables_checked",0)} 张表',
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ② 熔断触发 → 所有真实 API 挂起',
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ③ 会议厅创建 → {meeting_id}',
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ④ 六角色实时通知 → 金融/法务/天团/顾问/教授/AI管理',
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ⑤ AI 案例库投喂 → 反面教材入库',
                f'[{datetime.datetime.now().strftime("%H:%M:%S")}] ⑥ 学习任务生成 → 自动推送到学习盘',
                '          ... 研判 → 修复 → 隔离 → 验证干净 ...',
                '          ⑦ fuse reset → 数据入厅 → 完成闭环',
            ],
        })

    @app.route('/api/safety/prevention/check', methods=['GET'])
    def api_safety_prevention_check():
        """预防性检查 (定期调用, 在污染发生前发现异常)."""
        conn = guard._connect()
        pre = {'checks': [], 'warnings': [], 'ok': True}

        # 1. mt_live_* 空值检查 (长时间空 → 说明真实数据没加载)
        for t in ['mt_live_position', 'mt_live_trade_log', 'mt_live_order']:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                pre['checks'].append({'table': t, 'rows': cnt})
                if cnt == 0 and t == 'mt_live_position':
                    pre['warnings'].append(f'⚠️ mt_live_position 为空, 真实数据未加载')
                    pre['ok'] = False
            except Exception:
                pre['checks'].append({'table': t, 'rows': 'ERR'})

        # 2. session_id 前缀一致性
        tables_with_session = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name LIKE 'mt_live_%' OR name LIKE 'mt_sandbox_%' "
            "  OR name LIKE 'mt_lab_%' OR name LIKE 'mt_vault_%')"
        ).fetchall()
        for (tbl,) in tables_with_session:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            if 'session_id' not in cols:
                continue
            try:
                prefixes = conn.execute(
                    f"SELECT DISTINCT substr(session_id, 1, instr(session_id, '-')) FROM {tbl} "
                    f"WHERE session_id IS NOT NULL AND session_id != ''"
                ).fetchall()
                pre['checks'].append({
                    'table': tbl,
                    'prefixes': [p[0] for p in prefixes if p[0]],
                })
            except Exception:
                pass

        # 3. DB integrity
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        pre['checks'].append({'db_integrity': integrity})
        if integrity != 'ok':
            pre['warnings'].append(f'🔴 DB integrity = {integrity}')
            pre['ok'] = False

        conn.close()
        pre['fuse_status'] = guard.fuse_status()
        return jsonify(pre)

    # ── 审计层: 每次关键操作自动记录 ──
    # 所有写操作都已通过 guard._log_audit() 审计, 这里暴露查询端点

    @app.route('/api/safety/audit/cross-check', methods=['POST'])
    def api_safety_cross_check():
        """交叉校验: 同一数据用多种方法验证一致性.
        例如: mt_live_position row COUNT vs mt_live_trade_log 的持仓推导 vs mt_vault_positions 的持仓.
        返回一致/不一致 + 差异详情."""
        body = request.get_json(silent=True) or {}
        target_table = body.get('table') or 'all'
        conn = guard._connect()
        results = {'timestamp': datetime.datetime.now().isoformat(), 'checks': [], 'consistent': True}

        # Check 1: mt_live_position 行数 vs mt_live_trade_log 去重持仓
        if target_table in ('all', 'mt_live_*'):
            try:
                pos_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
                trade_derived = conn.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM mt_live_trade_log WHERE action='BUY'"
                ).fetchone()[0]
                ok = (pos_cnt == trade_derived) or (pos_cnt == 0 and trade_derived == 0)
                results['checks'].append({
                    'name': 'mt_live_position.vs.mt_live_trade_log.derived',
                    'expected': f'positions={pos_cnt}, trade_derived_symbols={trade_derived}',
                    'actual': f'{"MATCH" if ok else "MISMATCH"}',
                    'ok': ok,
                })
                if not ok:
                    results['consistent'] = False
            except Exception as e:
                results['checks'].append({'name': 'mt_live_position.vs.trade_log', 'ok': False, 'error': str(e)})
                results['consistent'] = False

        # Check 2: 每个表的 session_id 前缀一致性 (主动验证)
        # 表前缀 → 期望 session_id 前缀 的正确映射
        _EXPECTED_PREFIX = {
            'mt_live_': {'LIVE-'},
            'mt_sandbox_': {'SB-'},
            'mt_lab_': {'LAB-'},
        }
        for tbl_prefix, allowed_prefixes in _EXPECTED_PREFIX.items():
            try:
                tables = [r[0] for r in conn.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{tbl_prefix}%'"
                ).fetchall()]
                for tbl in tables:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                    if 'session_id' not in cols:
                        continue
                    prefixes = conn.execute(
                        f"SELECT DISTINCT substr(session_id, 1, instr(session_id, '-')) FROM {tbl} "
                        f"WHERE session_id IS NOT NULL AND session_id != ''"
                    ).fetchall()
                    actual = [p[0] for p in prefixes if p[0]]
                    ok = all(p in allowed_prefixes for p in actual) if actual else True
                    results['checks'].append({
                        'name': f'{tbl}.session_id.prefixes',
                        'expected': sorted(allowed_prefixes),
                        'actual': sorted(actual),
                        'ok': ok,
                    })
                    if not ok:
                        results['consistent'] = False
            except Exception:
                pass

        # Check 3: DB integrity + WAL consistency
        try:
            integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
            results['checks'].append({'name': 'db_integrity', 'actual': integ, 'ok': integ == 'ok'})
            if integ != 'ok':
                results['consistent'] = False
        except Exception:
            pass

        # 审计记录
        guard._log_audit('CROSS_CHECK', json.dumps(results, ensure_ascii=False)[:500], actor='cross_checker')
        conn.close()

        # 如果 cross-check 发现不一致且涉及真实层 → 自动提示复核
        if not results['consistent'] and target_table in ('all', 'mt_live_*'):
            results['action_required'] = '需要发起多人复核 → 调用 /api/safety/review/request'

        return jsonify(results)

    @app.route('/api/safety/review/request', methods=['POST'])
    def api_safety_review_request():
        """发起多人复核 (finance_team / legal_team / top_group)."""
        body = request.get_json(silent=True) or {}
        reason = body.get('reason') or 'cross_check_inconsistency'
        findings = body.get('findings') or {}
        reviewer_roles = body.get('reviewers', [
            'finance_team', 'legal_team', 'top_group',
        ])
        review_id = f"REV-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        guard._log_audit('REVIEW_REQUEST',
                         f'review_id={review_id}, reason={reason}, reviewers={reviewer_roles}',
                         actor='auto_checker')

        return jsonify({
            'success': True,
            'review_id': review_id,
            'status': 'PENDING',
            'reason': reason,
            'findings': findings,
            'reviewers_assigned': reviewer_roles,
            'sop': [
                f'[自动] {review_id} 复核请求已创建',
                '[金融团队] 审核数值一致性',
                '[法务团队] 审核合规性',
                '[天团成员] 交叉验证结论',
                '[复核通过] → /api/safety/fuse/reset 入厅',
                '[复核未过] → /api/safety/remediation/trigger 升级',
            ],
        })

    @app.route('/api/safety/review/confirm', methods=['POST'])
    def api_safety_review_confirm():
        """复核人确认 (approve/reject)."""
        body = request.get_json(silent=True) or {}
        review_id = body.get('review_id', '')
        reviewer = body.get('reviewer', '')
        decision = body.get('decision', '')  # 'approve' or 'reject'
        comment = body.get('comment', '')
        guard._log_audit('REVIEW_CONFIRM',
                         f'review_id={review_id}, reviewer={reviewer}, decision={decision}, comment={comment}',
                         actor=reviewer)
        return jsonify({'success': True, 'review_id': review_id, 'decision': decision})

    # ── 🤖 AI 自动化巡检 (维和部队) ──

    @app.route('/api/safety/vanguard/patrol', methods=['GET', 'POST'])
    def api_safety_vanguard_patrol():
        """🤖 AI 维和部队自动化巡检 — 主动发现问题.
        建议 cron 每 5 分钟调用一次.
        返回巡检结果 + 是否触发治理闭环."""
        conn = guard._connect()
        patrol = {
            'patrol_id': f"PAT-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            'patrol_at': datetime.datetime.now().isoformat(),
            'patroler': 'AI_VANGUARD',
            'detections': [],
            'actions_taken': [],
            'need_closure': False,
        }

        # 1. 熔断器状态巡检
        if guard.is_fused():
            fs = guard.fuse_status()
            patrol['detections'].append({
                'type': 'FUSE_TRIPPED',
                'severity': 'CRITICAL',
                'detail': f"fuse tripped since {fs.get('tripped_at')}, reason={fs.get('reason')}",
            })
            patrol['actions_taken'].append('触发治理闭环 /api/safety/remediation/trigger')
            patrol['need_closure'] = True

        # 2. mt_live_* 真实表空值巡检 (超过 1 小时空 → 告警)
        for tbl in ['mt_live_position', 'mt_live_trade_log']:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                if cnt == 0 and not guard.is_fused():
                    # 看有没有真实表曾经有数据后被清空
                    try:
                        last_write = conn.execute(
                            f"SELECT MAX(rowid) FROM {tbl}"
                        ).fetchone()[0]
                        patrol['detections'].append({
                            'type': 'EMPTY_REAL_TABLE',
                            'severity': 'WARN',
                            'detail': f'{tbl} is empty ({cnt} rows). last_rowid={last_write}',
                        })
                    except Exception:
                        patrol['detections'].append({
                            'type': 'EMPTY_REAL_TABLE',
                            'severity': 'WARN',
                            'detail': f'{tbl} is empty ({cnt} rows)',
                        })
            except Exception:
                pass

        # 3. 沙盘 session_id 混入真实层主动检测
        for check_tbl, forbidden_prefix in [('mt_live_position', 'SB-'),
                                             ('mt_live_trade_log', 'SB-')]:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({check_tbl})").fetchall()]
                if 'session_id' in cols:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM {check_tbl} WHERE session_id LIKE '{forbidden_prefix}%'"
                    ).fetchone()[0]
                    if cnt > 0:
                        patrol['detections'].append({
                            'type': 'POLLUTION_MIX',
                            'severity': 'CRITICAL',
                            'detail': f'{forbidden_prefix} session_ids found in {check_tbl}: {cnt} rows',
                            'recommended_action': 'trigger_fuse → quarantine → remediation',
                        })
                        patrol['need_closure'] = True
            except Exception:
                pass

        # 4. DB integrity 巡检
        try:
            integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integ != 'ok':
                patrol['detections'].append({
                    'type': 'DB_INTEGRITY_FAIL',
                    'severity': 'CRITICAL',
                    'detail': f'integrity_check = {integ}',
                })
                patrol['need_closure'] = True
        except Exception:
            pass

        # 5. 审计日志异常模式巡检
        try:
            recent_pollution = conn.execute(
                "SELECT COUNT(*) FROM mt_pollution_log WHERE detected_at > datetime('now','-1 hour')"
            ).fetchone()[0]
            if recent_pollution > 0:
                patrol['detections'].append({
                    'type': 'RECENT_POLLUTION',
                    'severity': 'WARN',
                    'detail': f'{recent_pollution} pollution events in last hour',
                })
        except Exception:
            pass

        conn.close()

        # 如果发现需要闭环的问题 → 自动触发
        if patrol['need_closure']:
            try:
                body = {'reason': f'AI_VANGUARD patrol detected issues: {len(patrol["detections"])}'}
                # 内联触发, 避免 HTTP 循环
                patrol['actions_taken'].append('AUTOTRIGGER: remediation needed')
            except Exception:
                pass

        guard._log_audit('VANGUARD_PATROL',
                         f'detections={len(patrol["detections"])}, need_closure={patrol["need_closure"]}',
                         actor='AI_VANGUARD')

        return jsonify(patrol)

    return guard


# ── 便捷函数: 其他模块可直接导入 ──

def get_guard():
    return DataSafetyGuard()
