#!/usr/bin/env python3
"""
🧊 Aurora 极光衍生维护系统 — engines/aurora_skill_registry.py
===============================================================
仙女座 (Andromeda) × 冰山 (Iceberg) 之上的统一衍生维护层。

功能:
  1. 统一注册表 — 4 类能力用一张表管理:
     • daemon           34 个 smart_mount 自动化进程
     • iceberg_domain    7  个冰山域
     • iceberg_self      5  个五自能力
     • role              8  个角色 (super_admin/admin/student/...)
  2. Seed 迁移 — 首次启动自动从散落硬编码迁移进 DB
  3. CRUD + 启用/禁用 — 运行时可开关任何能力
  4. 反向兼容 — 所有现有 smart_mount/iceberg_meta/role_registry
     改为"有 Aurora 表就读 Aurora, 没有就 fallback 硬编码"

数据库: mt_aurora_skills (flask-app/database/app.db)
"""
from __future__ import annotations
import os, sys, sqlite3, json, time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# 规则管道: 所有种子/迁移/升级必须走维护管道
from ai_engines.rules_engine.maintenance_pipeline import maintenance_pipeline

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = str(_PROJECT_ROOT / 'database' / 'app.db')

# ═══════════════════════════════════════════════════════════
# 4 类能力的 schema 定义 (统一字段)
# ═══════════════════════════════════════════════════════════
CAPABILITY_TYPES = {
    'daemon':        {'icon': '⚙️', 'label': '自动化守护进程', 'scope': 'system'},
    'iceberg_domain': {'icon': '🧊', 'label': '冰山域', 'scope': 'iceberg'},
    'iceberg_self':   {'icon': '💪', 'label': '五自能力', 'scope': 'iceberg'},
    'role':           {'icon': '👤', 'label': '系统角色', 'scope': 'permission'},
}

# ── 辅助: 从散落硬编码提取 ──────────────────────────────────
def _extract_daemons() -> List[Dict]:
    """从 ai_smart_mount_engine.SYSTEM_REQUIRED_DAEMONS 提取"""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT))
        from engines.ai_smart_mount_engine import SYSTEM_REQUIRED_DAEMONS
        rows = []
        for d in SYSTEM_REQUIRED_DAEMONS:
            rows.append({
                'skill_key': d['process_name'],
                'name': d['process_name'],
                'description': d.get('duty', ''),
                'capability_type': 'daemon',
                'driver_daemon': d['process_name'],
                'cycle_s': d.get('inspect_cycle', 300),
                'source': 'SYSTEM_REQUIRED_DAEMONS',
                'tags': json.dumps(['smart_mount','daemon'], ensure_ascii=False),
            })
        return rows
    except Exception:
        return []

def _extract_iceberg_domains() -> List[Dict]:
    """从 iceberg_meta_model.ICEBERG_DOMAINS 提取"""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT))
        from engines.iceberg_meta_model import ICEBERG_DOMAINS
        rows = []
        for k, v in ICEBERG_DOMAINS.items():
            rows.append({
                'skill_key': f'domain_{k}',
                'name': f"🧊 {v['label']}",
                'description': v.get('desc',''),
                'capability_type': 'iceberg_domain',
                'domain_key': k,
                'roles': json.dumps(v.get('roles',[]), ensure_ascii=False),
                'daemons': json.dumps(v.get('daemons',[]), ensure_ascii=False),
                'core_tables': json.dumps(v.get('core_tables',[]), ensure_ascii=False),
                'source': 'ICEBERG_DOMAINS',
                'tags': json.dumps(['iceberg','domain'], ensure_ascii=False),
            })
        return rows
    except Exception:
        return []

def _extract_iceberg_self() -> List[Dict]:
    """从 iceberg_meta_model.SELF_CAPABILITIES 提取"""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT))
        from engines.iceberg_meta_model import SELF_CAPABILITIES
        rows = []
        for k, v in SELF_CAPABILITIES.items():
            rows.append({
                'skill_key': k,
                'name': f"{v['icon']} {v['label']}",
                'description': v.get('desc',''),
                'capability_type': 'iceberg_self',
                'driver_daemon': v.get('driver_daemon',''),
                'cycle_s': v.get('interval_s', 300),
                'db_log': v.get('db_log',''),
                'trigger': json.dumps(v.get('trigger',[]), ensure_ascii=False),
                'action': json.dumps(v.get('action',[]), ensure_ascii=False),
                'source': 'SELF_CAPABILITIES',
                'tags': json.dumps(['iceberg','self','five_self'], ensure_ascii=False),
            })
        return rows
    except Exception:
        return []

def _extract_roles() -> List[Dict]:
    """从 role_registry.ROLE_REGISTRY 提取"""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT))
        from routes.role_registry import ROLE_REGISTRY
        rows = []
        for k, v in ROLE_REGISTRY.items():
            rows.append({
                'skill_key': f'role_{k}',
                'name': f"👤 {v.get('label',k)}",
                'description': v.get('desc',''),
                'capability_type': 'role',
                'role_key': k,
                'iceberg_domain': v.get('iceberg_domain',''),
                'permissions': json.dumps(v.get('permissions',[]), ensure_ascii=False),
                'pages': json.dumps(v.get('pages',[]), ensure_ascii=False),
                'source': 'ROLE_REGISTRY',
                'tags': json.dumps(['role','permission'], ensure_ascii=False),
            })
        return rows
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# AuroraSkillRegistry — 统一注册表
# ═══════════════════════════════════════════════════════════
class AuroraSkillRegistry:
    """
    Aurora 极光衍生维护系统 — 统一 skill-like 能力的注册表

    使用:
      from engines.aurora_skill_registry import aurora_registry
      aurora_registry.all()                  # 所有
      aurora_registry.by_type('daemon')      # 按类型
      aurora_registry.enabled('iceberg_self')# 仅启用的
      aurora_registry.toggle(key, True/False)# 运行时开关
      aurora_registry.seed_all()             # 从硬编码迁移
    """
    _TABLE = 'mt_aurora_skills'

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        self._init_table()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._db_path)
        db.row_factory = sqlite3.Row
        return db

    def _now(self) -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _init_table(self):
        db = self._db()
        db.executescript(f"""
        CREATE TABLE IF NOT EXISTS {self._TABLE} (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_key        TEXT UNIQUE NOT NULL,        -- 唯一键 (如 sys_heartbeat_writer / self_strengthen / role_super_admin)
            name             TEXT NOT NULL,                -- 显示名
            description      TEXT,                          -- 说明
            capability_type  TEXT NOT NULL,                 -- daemon / iceberg_domain / iceberg_self / role
            enabled          INTEGER NOT NULL DEFAULT 1,    -- 运行时开关
            driver_daemon    TEXT,                          -- 关联 daemon (可选)
            cycle_s          INTEGER,                       -- 周期秒数 (可选)
            db_log           TEXT,                          -- 日志表 (可选)
            domain_key       TEXT,                          -- 冰山域 key (可选)
            role_key         TEXT,                          -- 角色 key (可选)
            iceberg_domain   TEXT,                          -- 角色绑定的冰山域 (可选)
            health_override  REAL,                          -- 手动健康覆盖 (可选, NULL=自动)
            reason           TEXT,                           -- 停用/覆盖原因 (可选)
            source           TEXT,                           -- 来源 (硬编码模块名)
            tags             TEXT,                           -- JSON tags
            extra_json       TEXT,                           -- 额外字段 JSON (触发/动作/权限/页面等)
            version          TEXT DEFAULT 'v1.0.0',
            created_at       TEXT DEFAULT (datetime('now')),
            updated_at       TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_aurora_type    ON {self._TABLE}(capability_type);
        CREATE INDEX IF NOT EXISTS idx_aurora_enabled ON {self._TABLE}(enabled);
        """)
        db.commit()
        db.close()

    # ── Seed: 从散落硬编码迁移 (通过维护管道) ──
    @maintenance_pipeline(action="seed", risk="medium", operator="aurora_registry", exempt_daemon=True)
    def seed_all(self) -> Dict[str, int]:
        """一次性把 34 daemon + 7 域 + 5 自 + 8 角色 全部迁移进 DB"""
        all_rows = []
        all_rows.extend(_extract_daemons())
        all_rows.extend(_extract_iceberg_domains())
        all_rows.extend(_extract_iceberg_self())
        all_rows.extend(_extract_roles())

        db = self._db(); now = self._now()
        by_type: Dict[str, int] = {}
        inserted = 0
        for row in all_rows:
            # extra_json = 不属于基础字段的附加数据 (trigger/action/permissions/pages/core_tables 等)
            basic_keys = {'skill_key','name','description','capability_type','driver_daemon',
                          'cycle_s','db_log','domain_key','role_key','iceberg_domain','source','tags'}
            extra = {k:v for k,v in row.items() if k not in basic_keys and k not in {'enabled','health_override','reason','version'}}
            extra_json = json.dumps(extra, ensure_ascii=False) if extra else None

            try:
                db.execute(f"""
                    INSERT OR IGNORE INTO {self._TABLE}
                    (skill_key, name, description, capability_type, enabled, driver_daemon, cycle_s, db_log,
                     domain_key, role_key, iceberg_domain, source, tags, extra_json, version, updated_at)
                    VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,'{now}')""",
                    (row.get('skill_key'), row.get('name'), row.get('description',''),
                     row.get('capability_type'), row.get('driver_daemon'), row.get('cycle_s'),
                     row.get('db_log'), row.get('domain_key'), row.get('role_key'),
                     row.get('iceberg_domain'), row.get('source'), row.get('tags'),
                     extra_json, 'v1.0.0'))
                if db.total_changes > 0:
                    inserted += 1
                    t = row.get('capability_type','unknown')
                    by_type[t] = by_type.get(t, 0) + 1
            except Exception as e:
                print(f"[Aurora] seed 跳过 {row.get('skill_key')}: {e}")
        db.commit(); db.close()
        print(f"[Aurora] ✅ seed 完成: 新增 {inserted} 条 · 类型分布 {by_type}")
        return {'inserted': inserted, 'by_type': by_type}

    def count_by_type(self) -> Dict[str, int]:
        db = self._db()
        rows = db.execute(f"""
            SELECT capability_type, COUNT(*) as c FROM {self._TABLE}
            GROUP BY capability_type""").fetchall()
        db.close()
        return {r['capability_type']: r['c'] for r in rows}

    # ── CRUD ──
    def all(self, enabled_only: bool = False) -> List[Dict]:
        db = self._db()
        sql = f'SELECT * FROM {self._TABLE}'
        if enabled_only: sql += ' WHERE enabled=1'
        rows = [dict(r) for r in db.execute(sql).fetchall()]
        db.close()
        return rows

    def by_type(self, cap_type: str, enabled_only: bool = False) -> List[Dict]:
        db = self._db()
        sql = f'SELECT * FROM {self._TABLE} WHERE capability_type=?'
        params: list = [cap_type]
        if enabled_only: sql += ' AND enabled=1'
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
        db.close()
        return rows

    def get(self, skill_key: str) -> Optional[Dict]:
        db = self._db()
        r = db.execute(f'SELECT * FROM {self._TABLE} WHERE skill_key=?', (skill_key,)).fetchone()
        db.close()
        return dict(r) if r else None

    def toggle(self, skill_key: str, enabled: bool, reason: str = '') -> bool:
        db = self._db()
        cur = db.execute(f'SELECT id FROM {self._TABLE} WHERE skill_key=?', (skill_key,)).fetchone()
        if not cur:
            db.close(); return False
        db.execute(f"""UPDATE {self._TABLE} SET enabled=?, reason=?, updated_at=? WHERE skill_key=?""",
                    (1 if enabled else 0, reason, self._now(), skill_key))
        db.commit(); db.close()
        return True

    def set_health_override(self, domain_key: str, health: float | None, reason: str = '') -> bool:
        """对 iceberg_domain 类型设置手动健康覆盖"""
        db = self._db()
        db.execute(f"""UPDATE {self._TABLE} SET health_override=?, reason=?, updated_at=?
                        WHERE capability_type='iceberg_domain' AND domain_key=?""",
                    (health, reason, self._now(), domain_key))
        db.commit(); db.close()
        return True

    def update_meta(self, skill_key: str, **fields) -> bool:
        allowed = {'name','description','health_override','reason','cycle_s','version'}
        updates = {k:v for k,v in fields.items() if k in allowed}
        if not updates: return False
        set_clause = ', '.join(f'{k}=?' for k in updates) + f", updated_at='{self._now()}'"
        db = self._db()
        db.execute(f"UPDATE {self._TABLE} SET {set_clause} WHERE skill_key=?",
                   list(updates.values()) + [skill_key])
        db.commit(); db.close()
        return True

    def delete(self, skill_key: str) -> bool:
        db = self._db()
        db.execute(f'DELETE FROM {self._TABLE} WHERE skill_key=?', (skill_key,))
        db.commit(); db.close()
        return True

    # ── 反向兼容: 给散落模块用的查询 ──
    def daemon_enabled(self, daemon_name: str) -> bool:
        """smart_mount_engine 查某个 daemon 是否被 Aurora 禁用"""
        db = self._db()
        r = db.execute(f"SELECT enabled FROM {self._TABLE} WHERE capability_type='daemon' AND skill_key=?",
                       (daemon_name,)).fetchone()
        db.close()
        # Aurora 没记录 → 默认启用 (兼容)
        return r is None or bool(r['enabled'])

    def domain_health(self, domain_key: str) -> Optional[float]:
        """iceberg_consciousness 查某域是否有手动健康覆盖"""
        db = self._db()
        r = db.execute(f"""SELECT health_override FROM {self._TABLE}
                            WHERE capability_type='iceberg_domain' AND domain_key=?""",
                            (domain_key,)).fetchone()
        db.close()
        return r['health_override'] if r and r['health_override'] is not None else None

    def five_self_enabled(self, domain_key: str, self_key: str) -> bool:
        """查某域某自是否被覆盖禁用"""
        db = self._db()
        # 先查 iceberg_domain 绑定 override (domain_health 行)
        # Aurora 模型里 iceberg_domain 和 iceberg_self 是两张独立记录, 绑定关系通过 domain_key+self_key 组合
        # 简化实现: 查 mt_iceberg_binding_override (历史表)
        try:
            r = db.execute(
                "SELECT enabled FROM mt_iceberg_binding_override WHERE domain_key=? AND self_key=?",
                (domain_key, self_key)).fetchone()
        except Exception:
            r = None
        db.close()
        return (r is None) or bool(r['enabled'])

    # ── 状态 ──
    def status(self) -> Dict[str, Any]:
        db = self._db()
        total = db.execute(f'SELECT COUNT(*) FROM {self._TABLE}').fetchone()[0]
        enabled = db.execute(f'SELECT COUNT(*) FROM {self._TABLE} WHERE enabled=1').fetchone()[0]
        by_type = db.execute(f"""
            SELECT capability_type, COUNT(*) FROM {self._TABLE} GROUP BY capability_type""").fetchall()
        db.close()
        return {
            'subsystem': 'Aurora 极光衍生维护系统',
            'version': 'v1.0.0',
            'total': total,
            'enabled': enabled,
            'disabled': total - enabled,
            'by_type': {r[0]: r[1] for r in by_type},
        }


# ── CLI ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='🧊 Aurora 极光衍生维护系统')
    ap.add_argument('--seed', action='store_true', help='从散落硬编码迁移全部能力进 DB')
    ap.add_argument('--status', action='store_true', help='查看 Aurora 状态')
    ap.add_argument('--list', choices=['daemon','iceberg_domain','iceberg_self','role','all'], default='all')
    ap.add_argument('--toggle', nargs=2, metavar=('KEY','ON/OFF'), help='运行时开关')
    ap.add_argument('--count', action='store_true', help='按类型计数')
    args = ap.parse_args()

    aurora = AuroraSkillRegistry()

    if args.seed:
        r = aurora.seed_all()
        print(f"✅ Seed 完成: 新增 {r['inserted']} 条")
        for t, c in r['by_type'].items():
            print(f"   {t}: +{c}")
    elif args.status:
        import json as _j
        print(_j.dumps(aurora.status(), ensure_ascii=False, indent=2))
    elif args.count:
        import json as _j
        print(_j.dumps(aurora.count_by_type(), ensure_ascii=False, indent=2))
    elif args.toggle:
        key, state = args.toggle
        ok = aurora.toggle(key, state.lower() in ('1','on','true','yes'))
        print(f"{'✅' if ok else '❌'} toggle {key} → {state}")
    else:
        rows = aurora.by_type(args.list) if args.list != 'all' else aurora.all()
        for r in rows:
            icon = CAPABILITY_TYPES.get(r['capability_type'],{}).get('icon','')
            st = '✅' if r['enabled'] else '🚫'
            print(f"  {icon} {st} [{r['capability_type']:15s}] {r['skill_key']:35s} {r['name']}")
        print(f"\n共 {len(rows)} 条")

# 单例
aurora_registry = AuroraSkillRegistry()
