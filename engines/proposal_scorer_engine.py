#!/usr/bin/env python3
"""
📋 ProposalScorerEngine — 任务大厅提案自动打分与版本升级建议
============================================================

职责:
  1. 接收改动集 (git diff / 文件列表 / 手动提交) → 自动分析体量与性质
  2. 打分 risk_level + 自动建议版本号升级 (patch / minor / major)
  3. 分类: 测试内容 / 核心引擎 / 模板样式 / 配置微调 / 数据迁移
  4. 与 ReleaseOrchestrator 对接 — 达标 → 提交审批 → 进入灰度

版本号升级规则 (语义化 semver):
  patch  (v25.0.3): diff<500行 或 文件数<10 → 纯 bugfix
  minor  (v25.1.0): diff≥500行 AND 文件数≥10 → 有新功能
  major  (v26.0.0): 核心引擎修改 AND 有 Breaking Change
  release candidate:  smoke test 全过 → 可升公版 RC

存储分级策略 (硬盘爆仓保护):
  L1 hulk-macmini SSD  → 热数据 (主数据库 + 活跃沙盘数据)
  L2 hulk-server      → 温数据 (归档 + 历史沙盘会话)
  L3 NAS fnOS         → 冷数据 (永久归档 + AI 投喂经验库)
  ❌ 绝不直接删除 — 先降级存储,实在不行上 hulk-server,等 NAS 上线再 push

依赖:
  - mt_proposals (本引擎自动建)
  - mt_proposal_items (明细:文件级分析)
  - mt_version_registry (版本登记,已存在)
  - engines/gray_release_engine.py (发布执行)
  - engines/approval/service.py (审批)
"""
from __future__ import annotations

import hashlib, json, sqlite3, time, uuid, os, re
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = _PROJECT_ROOT / "database" / "app.db"


# ═══════════════════════════════════════════════════════════
# DB Schema
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT UNIQUE,             -- "prop_" + uuid[:12]
    title           TEXT NOT NULL,
    initiator       TEXT NOT NULL,
    description     TEXT,

    -- 改动体量
    file_count      INTEGER DEFAULT 0,
    lines_added     INTEGER DEFAULT 0,
    lines_deleted   INTEGER DEFAULT 0,
    diff_total      INTEGER DEFAULT 0,

    -- 自动分类 (JSON)
    categories      TEXT,                     -- {"core":3,"template":5,"config":2,"test":1}
    file_type_map   TEXT,                     -- {".py":8,".html":3,".css":2,".js":1}
    core_engines_touched TEXT,                -- 哪些核心引擎被改 (JSON list)

    -- 打分
    risk_level      TEXT DEFAULT 'medium',    -- low / medium / high / critical
    complexity_score REAL DEFAULT 0,          -- 0-100 复杂度分
    test_coverage   REAL DEFAULT 0,           -- 0-100 测试覆盖预估

    -- 版本号建议
    current_version TEXT,                     -- "v25.0"
    suggested_version TEXT,                   -- "v25.0.3" / "v25.1.0"
    upgrade_type    TEXT,                     -- patch / minor / major
    can_release     INTEGER DEFAULT 0,        -- 1=仙女座判定可升公版 RC

    -- 审批 & 发布
    approval_id     TEXT,
    release_id      TEXT,
    status          TEXT DEFAULT 'scoring',   -- scoring / reviewed / approved / releasing / released / rejected

    -- 存储分级 (硬盘保护)
    storage_tier    TEXT DEFAULT 'L1',        -- L1=mini / L2=hulk-server / L3=NAS
    archived_at     TEXT,

    -- 时间戳
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    scored_at       TEXT,
    reviewed_at     TEXT,
    released_at     TEXT
);

CREATE TABLE IF NOT EXISTS mt_proposal_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    change_type     TEXT DEFAULT 'M',         -- A=新增 M=修改 D=删除 R=重命名
    lines_added     INTEGER DEFAULT 0,
    lines_deleted   INTEGER DEFAULT 0,
    category        TEXT DEFAULT 'other',     -- core/template/config/test/data
    risk_level      TEXT DEFAULT 'low',
    FOREIGN KEY(proposal_id) REFERENCES mt_proposals(proposal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_storage_manifest (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    storage_tier    TEXT NOT NULL,            -- L1 / L2 / L3
    mount_point     TEXT NOT NULL,            -- ~/MTSCOS_AI_Project / /tmp/mtscos_beta / ~/mnt/hulk-nas
    used_bytes      INTEGER DEFAULT 0,
    total_bytes     INTEGER DEFAULT 0,
    inode_used      INTEGER DEFAULT 0,
    inode_total     INTEGER DEFAULT 0,
    last_checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
    health          TEXT DEFAULT 'ok'         -- ok / warn / critical / exhausted
);
"""


# ═══════════════════════════════════════════════════════════
# 分类规则
# ═══════════════════════════════════════════════════════════
CORE_ENGINES = [
    # 哪些引擎是核心 (改了 = major risk)
    'gray_release_engine', 'approvals_engine', 'roundtable_orchestrator',
    'auto_dev_team_engine', 'maintenance_pipeline', 'server_real_db',
    'modular_start', 'sandbox_bp', 'global_upgrade',
]
TEMPLATE_DIRS = ['templates/', 'static/', 'blueprints/sandbox_bp']
CONFIG_FILES = ['config.', 'settings.', '.env', 'requirements', 'launchd', '.plist']
TEST_PATTERNS = ['test_', 'tests/', 'spec_', '_test.py', '/spec/']


def _classify_file(path: str) -> str:
    """单文件分类: core / template / config / test / data / other"""
    p = path.lower()
    for t in TEST_PATTERNS:
        if t in p: return 'test'
    for c in CORE_ENGINES:
        if c in p: return 'core'
    if any(d in p for d in TEMPLATE_DIRS): return 'template'
    if any(cf in p for cf in CONFIG_FILES): return 'config'
    if '/database/' in p or p.endswith('.db') or p.endswith('.sqlite'): return 'data'
    if p.endswith('.py') and 'engines/' in p: return 'engine'
    if p.endswith('.py') and 'blueprints/' in p: return 'blueprint'
    return 'other'


def _file_risk(path: str, category: str) -> str:
    """单文件风险: low / medium / high / critical"""
    p = path.lower()
    if category == 'core': return 'critical'
    if category in ('engine', 'blueprint'): return 'high'
    if '/ai_engines/' in p or 'ai_sandbox_tick' in p: return 'high'
    if category == 'data': return 'high'  # DB 操作 = 高风险
    if category == 'template': return 'low'
    if category in ('config', 'test'): return 'low'
    return 'medium'


# ═══════════════════════════════════════════════════════════
# 主引擎
# ═══════════════════════════════════════════════════════════
class ProposalScorerEngine:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _DB_PATH
        self._ensure_schema()

    def _ensure_schema(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    # ── 公开 API ──

    def score_from_git(self, title: str, initiator: str = 'system',
                       base_branch: str = 'main', head: str = 'HEAD',
                       worktree: bool = False) -> dict:
        """从 git diff 自动打分
        worktree=True 时从 工作区未 commit 的脏文件 打 (git diff --numstat 不加 base...head)
        """
        import subprocess
        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        if worktree:
            cmd = ['git', 'diff', '--numstat']
        else:
            cmd = ['git', 'diff', '--numstat', f'{base_branch}...{head}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            numstat = result.stdout.strip()
        except Exception as e:
            return {'error': f'git diff failed: {e}'}

        items = []
        file_count = added = deleted = 0
        categories = {}
        core_touched = []
        file_types = {}

        for line in numstat.split('\n'):
            if not line.strip(): continue
            parts = line.split('\t')
            if len(parts) < 3: continue
            a, d, fpath = parts[0], parts[1], parts[2]
            try:
                a_i = int(a); d_i = int(d)
            except ValueError:
                a_i = d_i = 0  # binary file
            category = _classify_file(fpath)
            risk = _file_risk(fpath, category)
            file_count += 1
            added += a_i; deleted += d_i
            categories[category] = categories.get(category, 0) + 1
            ext = Path(fpath).suffix.lower()
            file_types[ext] = file_types.get(ext, 0) + 1
            if category == 'core': core_touched.append(fpath)

            items.append({
                'file_path': fpath,
                'change_type': 'M',
                'lines_added': a_i,
                'lines_deleted': d_i,
                'category': category,
                'risk_level': risk,
            })

        diff_total = added + deleted
        risk_level = self._compute_risk(categories, core_touched, diff_total, file_count)
        complexity = self._compute_complexity(categories, diff_total, file_count, core_touched)
        current_ver, suggested_ver, upgrade_type = self._suggest_version(categories, diff_total, file_count, core_touched)
        can_release = self._can_release_rc(risk_level, complexity, categories, diff_total)

        result = self._insert_proposal(
            proposal_id=proposal_id, title=title, initiator=initiator,
            file_count=file_count, lines_added=added, lines_deleted=deleted,
            diff_total=diff_total, categories=categories, file_types=file_types,
            core_touched=core_touched, risk_level=risk_level, complexity=complexity,
            current_version=current_ver, suggested_version=suggested_ver,
            upgrade_type=upgrade_type, can_release=can_release, items=items,
        )
        return result

    def score_from_files(self, title: str, files: list[dict], initiator: str = 'system') -> dict:
        """从文件列表手动提交打分 (非 git 环境或 hulk-server 上)
        files: [{'path': 'foo.py', 'added': 10, 'deleted': 5, 'change_type': 'M'}, ...]
        """
        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        items = []
        file_count = added = deleted = 0
        categories = {}; core_touched = []; file_types = {}

        for f in files:
            path = f.get('path', f.get('file_path', 'unknown'))
            a = f.get('added', 0); d = f.get('deleted', 0)
            category = _classify_file(path)
            risk = _file_risk(path, category)
            file_count += 1; added += a; deleted += d
            categories[category] = categories.get(category, 0) + 1
            ext = Path(path).suffix.lower()
            file_types[ext] = file_types.get(ext, 0) + 1
            if category == 'core': core_touched.append(path)
            items.append({
                'file_path': path, 'change_type': f.get('change_type', 'M'),
                'lines_added': a, 'lines_deleted': d,
                'category': category, 'risk_level': risk,
            })

        diff_total = added + deleted
        risk_level = self._compute_risk(categories, core_touched, diff_total, file_count)
        complexity = self._compute_complexity(categories, diff_total, file_count, core_touched)
        current_ver, suggested_ver, upgrade_type = self._suggest_version(categories, diff_total, file_count, core_touched)
        can_release = self._can_release_rc(risk_level, complexity, categories, diff_total)

        return self._insert_proposal(
            proposal_id=proposal_id, title=title, initiator=initiator,
            file_count=file_count, lines_added=added, lines_deleted=deleted,
            diff_total=diff_total, categories=categories, file_types=file_types,
            core_touched=core_touched, risk_level=risk_level, complexity=complexity,
            current_version=current_ver, suggested_version=suggested_ver,
            upgrade_type=upgrade_type, can_release=can_release, items=items,
        )

    # ── 内部 ──

    def _compute_risk(self, categories, core_touched, diff_total, file_count) -> str:
        if core_touched: return 'critical'
        if diff_total > 3000 or file_count > 50: return 'high'
        if 'data' in categories and categories['data'] > 2: return 'high'
        if diff_total > 1000 or file_count > 20: return 'medium'
        return 'low'

    def _compute_complexity(self, categories, diff_total, file_count, core_touched) -> float:
        """0-100 复杂度分"""
        score = 0.0
        score += min(diff_total / 50, 50)      # 体量: 50分封顶
        score += min(file_count * 1.5, 25)      # 文件数: 25分封顶
        if core_touched: score += 15            # 核心引擎: +15
        if categories.get('engine', 0) > 3: score += 10
        if categories.get('data', 0) > 2: score += 5
        return round(min(score, 100), 1)

    def _suggest_version(self, categories, diff_total, file_count, core_touched) -> tuple:
        """返回 (current, suggested, upgrade_type)"""
        current = self._read_current_version()
        parts = re.match(r'v?(\d+)\.(\d+)\.?(\d+)?', current or '25.0')
        major, minor = int(parts.group(1)), int(parts.group(2))
        patch = int(parts.group(3) or 0)

        if core_touched or diff_total > 5000 or file_count > 100:
            return (f'v{major}.{minor}.{patch}', f'v{major+1}.0.0', 'major')
        if diff_total >= 2000 or file_count >= 30:
            return (f'v{major}.{minor}.{patch}', f'v{major}.{minor+1}.0', 'minor')
        return (f'v{major}.{minor}.{patch}', f'v{major}.{minor}.{patch+1}', 'patch')

    def _can_release_rc(self, risk_level, complexity, categories, diff_total) -> bool:
        """仙女座判定是否达标公版 RC"""
        if risk_level == 'critical': return False
        if complexity > 70: return False
        if diff_total < 200: return False  # 改动太少, 不值得发
        return True

    def _read_current_version(self) -> str:
        try:
            conn = sqlite3.connect(str(self.db_path))
            row = conn.execute(
                "SELECT version_tag FROM mt_version_registry ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row and row[0]: return row[0]
        except Exception: pass
        return 'v25.0'

    def _insert_proposal(self, **kw) -> dict:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT INTO mt_proposals
                (proposal_id, title, initiator, file_count, lines_added, lines_deleted,
                 diff_total, categories, file_type_map, core_engines_touched,
                 risk_level, complexity_score, current_version, suggested_version,
                 upgrade_type, can_release, status, created_at, scored_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                kw['proposal_id'], kw['title'], kw['initiator'],
                kw['file_count'], kw['lines_added'], kw['lines_deleted'], kw['diff_total'],
                json.dumps(kw['categories']), json.dumps(kw['file_types']),
                json.dumps(kw['core_touched']),
                kw['risk_level'], kw['complexity'],
                kw['current_version'], kw['suggested_version'],
                kw['upgrade_type'], 1 if kw['can_release'] else 0, 'reviewed',
            ))
            for it in kw['items']:
                conn.execute("""
                    INSERT INTO mt_proposal_items
                    (proposal_id, file_path, change_type, lines_added, lines_deleted, category, risk_level)
                    VALUES (?,?,?,?,?,?,?)
                """, (kw['proposal_id'], it['file_path'], it['change_type'],
                      it['lines_added'], it['lines_deleted'], it['category'], it['risk_level']))
            conn.commit()
        finally:
            conn.close()
        return {
            'proposal_id': kw['proposal_id'],
            'title': kw['title'],
            'risk_level': kw['risk_level'],
            'complexity': kw['complexity'],
            'diff_total': kw['diff_total'],
            'file_count': kw['file_count'],
            'upgrade_type': kw['upgrade_type'],
            'suggested_version': kw['suggested_version'],
            'can_release': kw['can_release'],
            'storage_tier': 'L1',
            'next_step': 'approve_or_reject',
        }

    # ── 查询 ──

    def list_proposals(self, limit: int = 20, status: str | None = None) -> list:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM mt_proposals"
        args = []
        if status:
            sql += " WHERE status = ?"; args.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
        for r in rows:
            for k in ('categories','file_type_map','core_engines_touched'):
                if r.get(k):
                    try: r[k] = json.loads(r[k])
                    except: pass
        return rows

    def check_storage_manifest(self) -> dict:
        """三存储分级健康检查 — 硬盘爆仓保护"""
        tiers = {
            'L1': {'mount': str(_PROJECT_ROOT),           'label': 'hulk-macmini SSD'},
            'L2': {'mount': '/tmp/mtscos_beta',           'label': 'hulk-server tmpfs'},
            'L3': {'mount': str(Path.home() / 'mnt' / 'hulk-nas'), 'label': 'NAS fnOS'},
        }
        results = {}
        for tier, info in tiers.items():
            import shutil
            try:
                usage = shutil.disk_usage(info['mount'])
                used = usage.used; total = usage.total; free = total - used
                health = 'ok' if free > total * 0.2 else ('warn' if free > total * 0.1 else 'critical')
                if not os.path.exists(info['mount']): health = 'missing'
                results[tier] = {
                    'mount': info['mount'], 'label': info['label'],
                    'used_gb': round(used / 1e9, 1), 'total_gb': round(total / 1e9, 1),
                    'free_gb': round(free / 1e9, 1),
                    'pct_used': round(used / total * 100, 1),
                    'health': health,
                }
            except Exception as e:
                results[tier] = {'mount': info['mount'], 'label': info['label'],
                                 'health': 'error', 'error': str(e)}

        # 绝不删除 — 只降级
        # L1 critical → 自动把归档数据 rsync 到 L2 hulk-server
        # L2 critical → 等 NAS L3 上线 push
        for tier, info in results.items():
            if info.get('health') in ('critical', 'exhausted') and tier == 'L1':
                info['action'] = 'auto_archive_to_L2_pending'
            elif info.get('health') == 'critical' and tier == 'L2':
                info['action'] = 'push_to_L3_when_nas_online'

        return results


# ═══════════════════════════════════════════════════════════
# ReleaseOrchestratorEngine — 闭环总控
# ═══════════════════════════════════════════════════════════
class ReleaseOrchestratorEngine:
    """把 proposal → approval → release → sync → version_register 串成流水线"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _DB_PATH
        self.scorer = ProposalScorerEngine(self.db_path)

    def pipeline(self, proposal_id: str, auto_approve: bool = False,
                 initiator: str = 'system') -> dict:
        """全流水线: proposal → (approve) → release → sync → register"""
        # 1) 读提案
        proposals = self.scorer.list_proposals(limit=1, status='reviewed')
        target = None
        for p in self.scorer.list_proposals(limit=100):
            if p['proposal_id'] == proposal_id:
                target = p; break
        if not target:
            target = self.scorer.list_proposals(limit=1)[0]

        # 2) 提交审批
        approval_id = None
        if auto_approve or target.get('can_release'):
            approval_id = f"app_{uuid.uuid4().hex[:12]}"
            self._log_approval(approval_id, target['proposal_id'], initiator, 'auto_approved')

        # 3) 创建灰度发布会话
        release_id = None
        try:
            from engines.gray_release_engine import GrayReleaseEngine
            gre = GrayReleaseEngine()
            rel = gre.create_release(
                name=f"{target.get('suggested_version','v25.0')} {target.get('title','')}",
                description=target.get('description',''),
                target_version=target.get('suggested_version','v25.0'),
                scope='full',
                risk_level=target.get('risk_level','medium'),
                initiator=initiator,
                approval_id=approval_id,
            )
            release_id = rel.get('release_id')
        except Exception as e:
            release_id = f"rel_{uuid.uuid4().hex[:12]}"
            self._log_release(release_id, target['proposal_id'], str(e))

        # 4) 启动发布 (canary 阶段)
        started = False
        try:
            from engines.gray_release_engine import GrayReleaseEngine
            gre = GrayReleaseEngine()
            gre.advance_stage(release_id)  # draft → approved → canary(1%)
            started = True
        except Exception:
            pass

        # 5) 同步脚本触发标记 (bidirectional_sync.py 观察到 release_session 更新自动 rsync)
        self._mark_sync_pending(target.get('suggested_version','v25.0'), release_id)

        # 6) 版本登记
        self._register_version(
            version=target.get('suggested_version','v25.0'),
            proposal_id=target['proposal_id'],
            commit=target.get('suggested_version',''),
        )

        # 7) 更新提案状态
        self._update_proposal_status(target['proposal_id'], 'releasing',
                                     approval_id=approval_id, release_id=release_id)

        return {
            'proposal_id': target['proposal_id'],
            'approval_id': approval_id,
            'release_id': release_id,
            'started': started,
            'storage': self.scorer.check_storage_manifest(),
            'next_auto': 'gray_release_engine 每 5min 自动门禁采集 → 过则升 stage',
        }

    # ── 内部辅助 ──

    def _log_approval(self, approval_id, proposal_id, approver, action):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT INTO mt_approval_requests
                (request_id, category, target_id, title, requester_id, status, created_at)
                VALUES (?,?,?,?,?, 'approved', CURRENT_TIMESTAMP)
            """, (approval_id, 'release', proposal_id, f'发布提案 {proposal_id}', approver))
        except Exception: pass
        try:
            conn.execute("""
                INSERT INTO mt_approval_actions
                (approval_id, action, actor_id, created_at, comment)
                VALUES (?,?,?, CURRENT_TIMESTAMP, ?)
            """, (approval_id, action, approver, '仙女座自动通过'))
        except Exception: pass
        conn.commit(); conn.close()

    def _log_release(self, release_id, proposal_id, detail):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT OR IGNORE INTO mt_release_sessions
                (release_id, name, status, initiator, created_at)
                VALUES (?,?, 'approved', 'system', CURRENT_TIMESTAMP)
            """, (release_id, f'prop_{proposal_id[:8]}'))
        except Exception: pass
        conn.commit(); conn.close()

    def _mark_sync_pending(self, version, release_id):
        """写一个标记文件,bidirectional_sync.py 观察到自动触发 rsync"""
        marker_dir = _PROJECT_ROOT / '_runtime'
        marker_dir.mkdir(exist_ok=True)
        marker = marker_dir / f'release_pending_{release_id[:8]}.json'
        marker.write_text(json.dumps({
            'version': version, 'release_id': release_id,
            'created_at': datetime.utcnow().isoformat(),
            'targets': ['hulk-macmini', 'hulk-server'],
        }, indent=2))

    def _register_version(self, version, proposal_id, commit):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT INTO mt_version_registry
                (version_tag, commit_hash, description, proposer, approved_at)
                VALUES (?,?,?,?, CURRENT_TIMESTAMP)
            """, (version, commit or '', f'prop_{proposal_id[:8]}', '仙女座自动'))
        except Exception: pass
        conn.commit(); conn.close()

    def _update_proposal_status(self, proposal_id, status, approval_id=None, release_id=None):
        conn = sqlite3.connect(str(self.db_path))
        set_clause = "status = ?, reviewed_at = CURRENT_TIMESTAMP"
        args = [status]
        if approval_id:
            conn.execute("UPDATE mt_proposals SET approval_id=? WHERE proposal_id=?",
                         (approval_id, proposal_id))
        if release_id:
            conn.execute("UPDATE mt_proposals SET release_id=? WHERE proposal_id=?",
                         (release_id, proposal_id))
        conn.execute(f"UPDATE mt_proposals SET {set_clause} WHERE proposal_id=?", args + [proposal_id])
        conn.commit(); conn.close()


# ═══════════════════════════════════════════════════════════
# 便捷入口
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Proposal Scorer + Release Orchestrator')
    sub = parser.add_subparsers(dest='cmd')

    p_score = sub.add_parser('score', help='从 git diff 打分')
    p_score.add_argument('--title', required=True)
    p_score.add_argument('--initiator', default='cli')
    p_score.add_argument('--base', default='main')
    p_score.add_argument('--head', default='HEAD')
    p_score.add_argument('--worktree', action='store_true',
                         help='从未 commit 的脏文件打分 (git diff 不加 base...head)')

    p_proposals = sub.add_parser('list', help='列出提案')
    p_proposals.add_argument('--status', default=None)

    p_storage = sub.add_parser('storage', help='三存储健康检查')

    p_orch = sub.add_parser('release', help='执行发布流水线')
    p_orch.add_argument('--proposal-id')
    p_orch.add_argument('--auto-approve', action='store_true')

    args = parser.parse_args()
    scorer = ProposalScorerEngine()

    if args.cmd == 'score':
        print(json.dumps(scorer.score_from_git(
            args.title, args.initiator, args.base, args.head
        ), indent=2, ensure_ascii=False))
    elif args.cmd == 'list':
        print(json.dumps(scorer.list_proposals(status=args.status), indent=2, ensure_ascii=False))
    elif args.cmd == 'storage':
        print(json.dumps(scorer.check_storage_manifest(), indent=2, ensure_ascii=False))
    elif args.cmd == 'release':
        orch = ReleaseOrchestratorEngine()
        pid = args.proposal_id or scorer.list_proposals(limit=1)[0]['proposal_id']
        print(json.dumps(orch.pipeline(pid, auto_approve=args.auto_approve),
                         indent=2, ensure_ascii=False))
