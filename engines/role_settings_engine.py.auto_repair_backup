#!/usr/bin/env python3
"""
⚙️ 仙女座统一角色设置引擎 RoleSettingsEngine (v25.0)
======================================================
DB 深度绑定:
  mt_role_settings          — 通用设置 (can/features/iceberg/notifications 等 JSON)
  mt_teacher_configs        — 教师专属 (作业模板/评分标准/考勤规则)
  mt_professor_prefs        — 教授专属 (科研方向/AI模型偏好/评审配置)
  mt_counselor_configs      — 导员专属 (考勤阈值/预警规则/家访计划)
  mt_mentor_configs         — 导师专属 (门徒追踪模板/技能图谱/培养计划)
  mt_parent_configs         — 家长专属 (关注科目/成绩阈值/通知频率)
  mt_role_settings_audit    — 所有变更留痕审计

自动机制:
  - 首次启动从 role_registry.py 读取默认值 → 写入 DB
  - can/features 权限矩阵变更 → 自动同步到 system_container.ROLE_TO_PERM
  - 每次 set 操作 → 自动写 mt_role_settings_audit

API (内部/CLI):
  RoleSettingsEngine.get(role_key)           → 全部设置 (通用 + 专属)
  RoleSettingsEngine.set(role_key, section, key, value) → 原子写
  RoleSettingsEngine.bulk_set(role_key, {..})          → 批量写
  RoleSettingsEngine.audit(role_key)         → 变更历史
  RoleSettingsEngine.sync_from_registry()    → 从 role_registry.py 重新同步默认值
"""
from __future__ import annotations
import sys, os, sqlite3, json, uuid, hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = _PROJECT_ROOT / "database" / "app.db"


# ═══════════════════════════════════════════════════════════
# DB Schema (自动建)
# ═══════════════════════════════════════════════════════════
SCHEMA = """
-- 通用角色设置 (统一主表)
CREATE TABLE IF NOT EXISTS mt_role_settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key        TEXT UNIQUE NOT NULL,
    role_label      TEXT NOT NULL,
    iceberg_domain  TEXT DEFAULT 'general',
    perm_level      TEXT DEFAULT 'login',
    -- 核心设置 (JSON 自动序列化)
    can_json        TEXT DEFAULT '{}',         -- 权限矩阵 {write_wenquxing:true,...}
    features_json   TEXT DEFAULT '{}',         -- 功能开关 {teacher_workbench:true,...}
    notifications_json TEXT DEFAULT '{}',      -- 通知偏好 {email:true,dashboard:true}
    limits_json     TEXT DEFAULT '{}',         -- 频率限制/配额 {max_homeworks_per_day:10}
    extra_json      TEXT DEFAULT '{}',         -- 扩展字段
    -- 元数据
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by      TEXT DEFAULT 'andromeda',
    updated_from    TEXT DEFAULT 'auto_sync'
);

-- 专属设置表 (5 角色)
CREATE TABLE IF NOT EXISTS mt_teacher_configs (
    role_key        TEXT PRIMARY KEY DEFAULT 'teacher',
    homework_template TEXT DEFAULT '',
    grading_scale   TEXT DEFAULT 'A,B,C,D,F',
    attendance_threshold REAL DEFAULT 0.8,     -- 80% 出勤率
    auto_grade      INTEGER DEFAULT 0,         -- 是否 AI 自动批改
    subject_focus   TEXT DEFAULT '',
    office_hours    TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(role_key) REFERENCES mt_role_settings(role_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_professor_prefs (
    role_key        TEXT PRIMARY KEY DEFAULT 'professor',
    research_fields TEXT DEFAULT '',
    ai_model_preference TEXT DEFAULT 'qwen2.5:14b-q5',
    paper_review_mode TEXT DEFAULT 'double-blind',
    grant_deadlines TEXT DEFAULT '',
    lab_size_limit  INTEGER DEFAULT 20,
    conference_alerts INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(role_key) REFERENCES mt_role_settings(role_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_counselor_configs (
    role_key        TEXT PRIMARY KEY DEFAULT 'counselor',
    attendance_warn_threshold REAL DEFAULT 0.7,
    attendance_critical_threshold REAL DEFAULT 0.5,
    parent_visit_interval_days INTEGER DEFAULT 30,
    mental_health_check_interval INTEGER DEFAULT 14,
    class_size      INTEGER DEFAULT 50,
    grade_focus     TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(role_key) REFERENCES mt_role_settings(role_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_mentor_configs (
    role_key        TEXT PRIMARY KEY DEFAULT 'mentor',
    disciple_tracking_template TEXT DEFAULT '',
    skill_graph_enabled INTEGER DEFAULT 1,
    checkin_interval_days INTEGER DEFAULT 7,
    milestone_review_enabled INTEGER DEFAULT 1,
    max_disciples   INTEGER DEFAULT 15,
    training_plan_template TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(role_key) REFERENCES mt_role_settings(role_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_parent_configs (
    role_key        TEXT PRIMARY KEY DEFAULT 'parent',
    watched_subjects TEXT DEFAULT '',
    grade_alert_threshold REAL DEFAULT 60.0,  -- <60 分告警
    notification_frequency TEXT DEFAULT 'daily', -- realtime/hourly/daily/weekly
    child_tracking_enabled INTEGER DEFAULT 1,
    privacy_mode    INTEGER DEFAULT 0,        -- 不展示孩子排名
    read_only_mode  INTEGER DEFAULT 1,        -- 默认只读
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(role_key) REFERENCES mt_role_settings(role_key) ON DELETE CASCADE
);

-- 审计日志 (所有变更自动留痕)
CREATE TABLE IF NOT EXISTS mt_role_settings_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key        TEXT NOT NULL,
    section         TEXT NOT NULL,             -- can/features/notifications/limits/专属表名
    field           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      TEXT DEFAULT 'andromeda',
    changed_from    TEXT DEFAULT 'api',
    changed_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    client_ip       TEXT
);

CREATE INDEX IF NOT EXISTS idx_rs_role_key ON mt_role_settings(role_key);
CREATE INDEX IF NOT EXISTS idx_audit_role_key ON mt_role_settings_audit(role_key);
CREATE INDEX IF NOT EXISTS idx_audit_section ON mt_role_settings_audit(section);
"""


# ═══════════════════════════════════════════════════════════
# RoleSettingsEngine — 统一入口
# ═══════════════════════════════════════════════════════════
class RoleSettingsEngine:
    """仙女座统一角色设置引擎 — DB 深度绑定"""

    ROLE_KEYS = ['super_admin', 'admin', 'student', 'teacher', 'professor', 'counselor', 'mentor', 'parent']
    EXCLUSIVE_TABLES = {
        'teacher':    'mt_teacher_configs',
        'professor':  'mt_professor_prefs',
        'counselor':  'mt_counselor_configs',
        'mentor':     'mt_mentor_configs',
        'parent':     'mt_parent_configs',
    }

    def __init__(self, db_path: Path = _DB_PATH):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        # 启动时自动从 role_registry.py 同步默认值 (如果 DB 为空)
        self._ensure_seeded()

    # ── 种子: 从 role_registry.py 读取默认值 → 写入 DB ──
    def _ensure_seeded(self):
        try:
            c = self.db.cursor()
            c.execute("SELECT COUNT(*) FROM mt_role_settings")
            if c.fetchone()[0] > 0:
                return  # 已有数据
            self.sync_from_registry()
        except Exception as e:
            print(f"  [settings] seed skip: {e}")

    def sync_from_registry(self) -> int:
        """从 role_registry.py 同步所有角色默认值 → mt_role_settings + 专属表"""
        try:
            sys.path.insert(0, str(_PROJECT_ROOT))
            from routes.role_registry import ROLE_REGISTRY
        except ImportError:
            print("  [settings] sync: role_registry.py not found, 使用内置默认")
            ROLE_REGISTRY = self._builtin_defaults()

        c = self.db.cursor()
        seeded = 0
        for key, info in ROLE_REGISTRY.items():
            c.execute("SELECT role_key FROM mt_role_settings WHERE role_key=?", (key,))
            if c.fetchone():
                continue  # 已有, 不覆盖

            can = info.get('can', {})
            features = info.get('features', {})
            c.execute(
                "INSERT INTO mt_role_settings "
                "(role_key, role_label, iceberg_domain, perm_level, can_json, features_json) "
                "VALUES (?,?,?,?,?,?)",
                (key, info.get('label', key), info.get('iceberg_domain', 'general'),
                 info.get('perm_level', 'login'),
                 json.dumps(can, ensure_ascii=False),
                 json.dumps(features, ensure_ascii=False)))
            self._init_exclusive_defaults(key)
            seeded += 1
        self.db.commit()
        print(f"  [settings] 🔄 从 role_registry.py 同步 {seeded} 个角色默认值")
        return seeded

    def _builtin_defaults(self) -> Dict:
        """role_registry.py 不可用时的内置默认"""
        return {
            'super_admin': {'label': '超级管理员', 'perm_level': 'super_admin',
                'iceberg_domain': 'ALL', 'can': {'write_wenquxing': True, 'manage_user': True, 'manage_daemon': True}},
            'admin':       {'label': '管理员', 'perm_level': 'admin',
                'iceberg_domain': 'iceberg_admin', 'can': {'write_wenquxing': False, 'manage_user': True}},
            'student':     {'label': '学生', 'perm_level': 'login',
                'iceberg_domain': 'wenquxing', 'can': {'write_wenquxing': True, 'take_exam': True}},
            'teacher':     {'label': '教师', 'perm_level': 'login',
                'iceberg_domain': 'education', 'can': {'write_wenquxing': False, 'assign_homework': True}},
            'professor':   {'label': '教授', 'perm_level': 'login',
                'iceberg_domain': 'education_research', 'can': {'write_wenquxing': False, 'ai_workbench': True}},
            'counselor':   {'label': '导员', 'perm_level': 'login',
                'iceberg_domain': 'education_wellness', 'can': {'write_wenquxing': False, 'attendance': True}},
            'mentor':      {'label': '导师', 'perm_level': 'login',
                'iceberg_domain': 'education_mentorship', 'can': {'write_wenquxing': False, 'track_disciples': True}},
            'parent':      {'label': '家长', 'perm_level': 'login',
                'iceberg_domain': 'education_parent', 'can': {'write_wenquxing': False, 'view_child_score': True}},
        }

    def _init_exclusive_defaults(self, role_key: str):
        """初始化专属表默认值 (INSERT OR IGNORE)"""
        table_map = {
            'teacher': ('mt_teacher_configs', {}),
            'professor': ('mt_professor_prefs', {}),
            'counselor': ('mt_counselor_configs', {}),
            'mentor': ('mt_mentor_configs', {}),
            'parent': ('mt_parent_configs', {}),
        }
        if role_key in table_map:
            table, _ = table_map[role_key]
            c = self.db.cursor()
            c.execute(f"INSERT OR IGNORE INTO {table} (role_key) VALUES (?)", (role_key,))

    # ── GET ──
    def get(self, role_key: str) -> Optional[Dict]:
        """获取某个角色的全部设置 (通用 + 专属 + audit)"""
        c = self.db.cursor()
        base = c.execute("SELECT * FROM mt_role_settings WHERE role_key=?", (role_key,)).fetchone()
        if not base:
            return None
        result = dict(base)
        # JSON 字段反序列化
        for jf in ['can_json', 'features_json', 'notifications_json', 'limits_json', 'extra_json']:
            try:
                result[jf.replace('_json','')] = json.loads(result.pop(jf) or '{}')
            except Exception:
                result[jf.replace('_json','')] = {}
        # 专属表
        if role_key in self.EXCLUSIVE_TABLES:
            t = self.EXCLUSIVE_TABLES[role_key]
            exc = c.execute(f"SELECT * FROM {t} WHERE role_key=?", (role_key,)).fetchone()
            if exc:
                result['exclusive'] = dict(exc)
        # 最近 5 条 audit
        audits = c.execute(
            "SELECT * FROM mt_role_settings_audit WHERE role_key=? ORDER BY changed_at DESC LIMIT 5",
            (role_key,)).fetchall()
        result['recent_audits'] = [dict(a) for a in audits]
        return result

    def list_all(self) -> List[Dict]:
        """列出所有角色设置"""
        return [self.get(k) for k in self.ROLE_KEYS]

    # ── SET (原子字段写) ──
    def set(self, role_key: str, section: str, key: str, value: Any,
            changed_by: str = 'api', changed_from: str = 'api') -> bool:
        """
        原子修改: section 可为 can/features/notifications/limits/extra 或专属表名
        例: set('teacher','can','assign_homework',True)
            set('teacher','mt_teacher_configs','attendance_threshold',0.85)
        """
        c = self.db.cursor()
        # 读旧值
        cur = self.get(role_key)
        if not cur:
            print(f"  [settings] {role_key} 不存在"); return False

        old_val = None; new_val = None

        if section in ('can', 'features', 'notifications', 'limits', 'extra'):
            # 通用 JSON 字段
            section_key = section + '_json'
            data = cur.get(section, {})
            old_val = data.get(key)
            data[key] = value
            new_val = value
            c.execute(
                f"UPDATE mt_role_settings SET {section_key}=?, updated_at=?, updated_by=?, updated_from=? WHERE role_key=?",
                (json.dumps(data, ensure_ascii=False),
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 changed_by, changed_from, role_key))
        elif section in self.EXCLUSIVE_TABLES.values():
            # 专属表字段
            c.execute(f"PRAGMA table_info({section})")
            cols = [r[1] for r in c.fetchall()]
            if key not in cols:
                print(f"  [settings] {section} 无字段 {key}"); return False
            old_row = c.execute(f"SELECT {key} FROM {section} WHERE role_key=?", (role_key,)).fetchone()
            old_val = old_row[0] if old_row else None
            c.execute(f"UPDATE {section} SET {key}=?, updated_at=? WHERE role_key=?",
                      (value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), role_key))
            new_val = value
        else:
            print(f"  [settings] 未知 section: {section}"); return False

        # 写 audit
        c.execute(
            "INSERT INTO mt_role_settings_audit (role_key, section, field, old_value, new_value, changed_by, changed_from) "
            "VALUES (?,?,?,?,?,?,?)",
            (role_key, section, key,
             json.dumps(old_val, ensure_ascii=False) if old_val is not None else None,
             json.dumps(new_val, ensure_ascii=False) if new_val is not None else None,
             changed_by, changed_from))
        self.db.commit()

        # 同步 can 权限变更 → system_container.ROLE_TO_PERM (可选)
        if section == 'can' and key in ('write_wenquxing', 'manage_user', 'manage_daemon'):
            print(f"  [settings] ⚠️ can.{key} 变更已落库 → 建议同步 system_container.ROLE_TO_PERM")

        return True

    def bulk_set(self, role_key: str, updates: Dict, changed_by: str = 'api', changed_from: str = 'api') -> int:
        """批量设置: updates = {'can':{'key':val}, 'features':{'k':v}, 'mt_teacher_configs':{'field':val}}"""
        count = 0
        for section, fields in updates.items():
            for k, v in fields.items():
                if self.set(role_key, section, k, v, changed_by, changed_from):
                    count += 1
        return count

    # ── AUDIT ──
    def audit(self, role_key: str, limit: int = 50) -> List[Dict]:
        c = self.db.cursor()
        rows = c.execute(
            "SELECT * FROM mt_role_settings_audit WHERE role_key=? ORDER BY changed_at DESC LIMIT ?",
            (role_key, limit)).fetchall()
        return [dict(r) for r in rows]

    # ── CLUSTER DASHBOARD 汇总 ──
    def cluster_summary(self) -> Dict:
        """所有角色设置的汇总视图 (供 admin Dashboard)"""
        c = self.db.cursor()
        roles = c.execute("SELECT role_key, role_label, iceberg_domain, perm_level FROM mt_role_settings").fetchall()
        summary = []
        for r in roles:
            a = c.execute("SELECT COUNT(*) FROM mt_role_settings_audit WHERE role_key=?", (r['role_key'],)).fetchone()[0]
            summary.append({
                'role_key': r['role_key'],
                'label': r['role_label'],
                'domain': r['iceberg_domain'],
                'perm_level': r['perm_level'],
                'audit_count': a,
                'has_exclusive': r['role_key'] in self.EXCLUSIVE_TABLES,
            })
        total_audits = c.execute("SELECT COUNT(*) FROM mt_role_settings_audit").fetchone()[0]
        return {'roles': summary, 'total_audits': total_audits, 'role_count': len(summary)}


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="⚙️ 仙女座统一角色设置引擎")
    ap.add_argument('--sync', action='store_true', help="从 role_registry.py 同步默认值")
    ap.add_argument('--list', action='store_true', help="列出全部角色设置")
    ap.add_argument('--get', metavar='ROLE_KEY', help="获取单个角色设置")
    ap.add_argument('--set', nargs=4, metavar=('ROLE','SECTION','KEY','VALUE'),
                    help="设置字段: teacher can assign_homework true")
    ap.add_argument('--audit', metavar='ROLE_KEY', help="审计日志")
    ap.add_argument('--summary', action='store_true', help="Dashboard 汇总")
    args = ap.parse_args()

    eng = RoleSettingsEngine()

    if args.sync:
        n = eng.sync_from_registry(); print(f"✅ 同步 {n} 个角色")
    elif args.list:
        for r in eng.list_all():
            print(f"  🟢 {r['role_key']} ({r['role_label']}) domain={r['iceberg_domain']} perm={r['perm_level']}")
            if r.get('exclusive'):
                print(f"    专属表: {list(r['exclusive'].keys())}")
    elif args.get:
        d = eng.get(args.get)
        if d: print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        else: print(f"❌ {args.get} 不存在")
    elif args.set:
        r, s, k, v = args.set
        # 尝试自动类型转换
        if v.lower() == 'true': v = True
        elif v.lower() == 'false': v = False
        elif v.replace('.','',1).isdigit(): v = float(v) if '.' in v else int(v)
        ok = eng.set(r, s, k, v, changed_by='cli', changed_from='cli')
        print(f"✅ 设置成功" if ok else f"❌ 失败")
    elif args.audit:
        for a in eng.audit(args.audit):
            print(f"  [{a['changed_at']}] {a['section']}.{a['field']} {a['old_value']} → {a['new_value']} by {a['changed_by']}@{a['changed_from']}")
    elif args.summary:
        print(json.dumps(eng.cluster_summary(), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
