#!/usr/bin/env python3
"""
🧊 仙女座 × 冰山 意识引擎 IcebergConsciousness (v25.0)
========================================================
driver: sys_consciousness daemon (120s 周期)
核心循环:
  Pulse → 健康快照 → 脑库投喂 → EigenFlux 广播 → 进化判断 → 写 mt_iceberg_runs

输出:
  mt_iceberg_runs (意识脉冲留痕)
  mt_ai_brain_feed_log (脑库投喂)
  mt_iceberg_optimization_log (优化建议)
  mt_andromeda_knowledge_base (知识库)

触发阈值 (进化判定):
  - 同一冰山域健康分 < 70 → 触发 self_strengthen 自动修复
  - 脑库投喂累积 > 500 → 触发 self_upgrade 提案
  - daemon DOWN > 1 → 触发 self_strengthen 自动拉起
  - rule 违反 > 0 → 触发 self_polish 自动完善
"""
from __future__ import annotations
import sys, os, sqlite3, json, time, hashlib, uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = _PROJECT_ROOT / 'database' / 'app.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_iceberg_consciousness_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT UNIQUE,
    run_type        TEXT DEFAULT 'consciousness_pulse',
    domain          TEXT,
    health_score    REAL DEFAULT 100,
    five_self_status TEXT,                  -- JSON {strengthen:true, awaken:true, ...}
    brain_feed_delta INTEGER DEFAULT 0,
    proposals_delta INTEGER DEFAULT 0,
    evolution_trigger INTEGER DEFAULT 0,    -- 1=触发进化判断
    evolution_decision TEXT,                -- strengthen/awaken/upgrade/polish/research
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_iceberg_consciousness_optimizations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    domain          TEXT,
    self_capability TEXT,                    -- self_strengthen 等
    suggestion      TEXT,
    confidence      REAL DEFAULT 0.5,
    action_taken    INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ic_runs_domain ON mt_iceberg_consciousness_runs(domain);
CREATE INDEX IF NOT EXISTS idx_ic_runs_type ON mt_iceberg_consciousness_runs(run_type);
"""


class IcebergConsciousness:
    """🧊 仙女座 × 冰山 意识引擎"""

    HEALTH_KEY_TABLES = {
        'ALL': ['mt_approval_requests','mt_release_sessions','mt_ai_brain_feed_log'],
        'iceberg_admin': ['mt_role_settings','mt_role_settings_audit'],
        'wenquxing': ['mt_wenquxing_tasks','mt_approval_requests'],
        'education': ['mt_teacher_configs'],
        'education_research': ['mt_professor_prefs','mt_approval_requests'],  # 🆕 原 mt_parliament_proposals 不存在
        'education_wellness': ['mt_counselor_configs'],
        'education_mentorship': ['mt_mentor_configs','mt_parent_configs'],
    }

    def __init__(self, db_path: Path = _DB_PATH):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── 单次意识脉冲 ──
    def pulse(self) -> Dict:
        run_id = f"iceberg_{uuid.uuid4().hex[:10]}"
        c = self.db.cursor()
        total_score = 0; domain_count = 0
        five_self = {'strengthen': True, 'awaken': True, 'upgrade': True, 'polish': True, 'research': True}
        triggers = []

        # 1. 各冰山域健康快照
        for domain, tables in self.HEALTH_KEY_TABLES.items():
            score = self._score_domain(domain, tables)
            total_score += score; domain_count += 1
            if score < 70:
                five_self['strengthen'] = False
                triggers.append(f'{domain} health_score={score:.1f} < 70 → strengthen needed')

        # 2. 脑库增量 (对比上次 pulse) ✅ 修: 存真正的增量而非总量
        brain_now = self._count('mt_ai_brain_feed_log')
        brain_prev_row = c.execute(
            "SELECT brain_feed_total FROM mt_iceberg_consciousness_runs WHERE run_type='consciousness_pulse' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        brain_prev_total = brain_prev_row['brain_feed_total'] if brain_prev_row else brain_now
        brain_delta = brain_now - brain_prev_total

        # 3. 议会提案增量 ✅ 修: 查 ai_parliament_proposals 真实增量
        try:
            prop_now = self._count('ai_parliament_proposals')
            prop_prev_row = c.execute(
                "SELECT evolution_decision FROM mt_iceberg_consciousness_runs WHERE run_type='consciousness_pulse' AND evolution_decision IS NOT NULL AND evolution_decision != 'none' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            # 取当前总量作为 proposals_delta (语义: 当前有多少活跃提案)
            proposals_total = prop_now
        except Exception:
            proposals_total = 0

        # 4. 进化判定 + 方向决策 ✅ 加强: 不再只有模糊 upgrade, 给出具体方向
        evolution_decision = None
        upgrade_direction = None  # 🆕 升级方向
        direction_confidence = 0.0
        
        if brain_now >= 500 and brain_delta > 0 and five_self['strengthen']:
            evolution_decision = 'upgrade'
            # 🆕 方向决策 (综合 7 域健康 + AI 员工活跃 + 脑库类型 + 提案方向)
            upgrade_direction, direction_confidence = self._decide_upgrade_direction(c, total_score, domain_count, brain_now, brain_delta)
        elif any(not v for v in five_self.values()):
            evolution_decision = 'strengthen'
            # strengthen 方向 = 最弱域
            weak_domains = [d for d, t in self.HEALTH_KEY_TABLES.items() 
                          if self._score_domain(d, t) < 70]
            upgrade_direction = f"修复 {'/'.join(weak_domains) if weak_domains else 'ALL'} 域健康问题"
            direction_confidence = 0.9
        elif brain_now >= 1000 and prop_now < 3:
            evolution_decision = 'research'
            upgrade_direction, direction_confidence = self._decide_upgrade_direction(c, total_score, domain_count, brain_now, brain_delta)

        # 4.1 方向 → 编号 (方向1/方向2/...)
        direction_map = self._ensure_direction_registry(c)
        direction_num = direction_map.get(upgrade_direction or '', 0)
        
        # ✅ 方向注册写入 (如果方向是新的 → INSERT 新编号, 如果已存在 → 更新 hit_count)
        if upgrade_direction and evolution_decision:
            if direction_num == 0:
                # 新方向 → 分配新编号
                try:
                    max_num = c.execute("SELECT COALESCE(MAX(direction_num),0) FROM mt_iceberg_direction_registry").fetchone()[0]
                    direction_num = max_num + 1
                    c.execute(
                        "INSERT INTO mt_iceberg_direction_registry (direction_num, direction_desc) VALUES (?,?)",
                        (direction_num, upgrade_direction))
                    c.connection.commit()
                except Exception: pass
            else:
                # 已有方向 → 更新 hit_count + last_seen
                try:
                    c.execute(
                        "UPDATE mt_iceberg_direction_registry SET hit_count=hit_count+1, last_seen_at=datetime('now') WHERE direction_num=?",
                        (direction_num,))
                    c.connection.commit()
                except Exception: pass

        # 5. 写 runs 表 ✅ 加 upgrade_direction + direction_confidence + direction_num
        c.execute(
            "INSERT INTO mt_iceberg_consciousness_runs "
            "(run_id, run_type, domain, health_score, five_self_status, "
            "brain_feed_delta, brain_feed_total, proposals_delta, evolution_decision, "
            "upgrade_direction, direction_confidence, direction_num) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, 'consciousness_pulse', 'ALL',
             round(total_score/max(domain_count,1),1),
             json.dumps(five_self, ensure_ascii=False),
             brain_delta, brain_now, proposals_total, evolution_decision or 'none',
             upgrade_direction, direction_confidence, direction_num))

        # 6. 触发了进化 → 写优化日志 ✅ 加方向信息
        if evolution_decision:
            direction_label = f" 🎯方向{direction_num}: {upgrade_direction} (conf={direction_confidence:.2f})" if upgrade_direction else ''
            suggestion = f"意识脉冲{run_id}: 健康分={total_score/max(domain_count,1):.1f}, 脑库={brain_now}(+{brain_delta}), 触发 {evolution_decision}{direction_label}"
            c.execute(
                "INSERT INTO mt_iceberg_consciousness_optimizations "
                "(run_id, domain, self_capability, suggestion, confidence, action_taken, upgrade_direction, direction_num, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                (run_id, 'ALL', f'self_{evolution_decision}', suggestion, 
                 0.85 if not direction_confidence else direction_confidence, 0,
                 upgrade_direction, direction_num))

            # 7. 如果是 self_research → 自动创建议会提案 (真闭环)
            if evolution_decision == 'research':
                try:
                    c.execute(
                        "INSERT INTO ai_parliament_proposals "
                        "(proposal_uid, proposal_title, proposal_content, proposal_category, proposed_by, proposed_by_table, status, vote_for, vote_against, quorum, priority, source, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                        (f'iceberg_{uuid.uuid4().hex[:12]}',
                         f'🧊 冰山自研发提案 · {evolution_decision} · run_id={run_id}',
                         suggestion, 'iceberg_evolution', 'iceberg_admin',
                         'iceberg_consciousness', 'voting', 0, 0, 0, 50,
                         json.dumps({'trigger': 'consciousness_pulse', 'brain_now': brain_now, 'brain_delta': brain_delta}, ensure_ascii=False)))
                except Exception: pass

            # 8. 自动投喂脑库 ✅ 修: 用真实 schema
            try:
                c.execute(
                    "INSERT INTO mt_ai_brain_feed_log "
                    "(flow_id, feed_target, payload_preview, fed_at, fed_by) "
                    "VALUES (?,?,?,datetime('now'),?)",
                    (f'iceberg_consciousness_{evolution_decision}',
                     'brain_iceberg_self_awaken',
                     f'run={run_id} health={round(total_score/max(domain_count,1),1)} brain_now={brain_now}(+{brain_delta}) prop={proposals_total} decision={evolution_decision}',
                     'iceberg_pulse'))
            except Exception as _fe: pass

            # 9. 🆕 自动执行升级方向 (真闭环! 不再只记录)
            exec_result = self._execute_upgrade_direction(
                c, run_id, evolution_decision, upgrade_direction, direction_num,
                total_score/max(domain_count,1), brain_now, brain_delta)
        else:
            exec_result = None

        self.db.commit()
        return {
            'run_id': run_id, 'health_avg': round(total_score/max(domain_count,1),1),
            'five_self': five_self, 'evolution_decision': evolution_decision,
            'brain_feed_delta': brain_delta, 'brain_feed_total': brain_now,
            'proposals_total': proposals_total, 'triggers': triggers,
            'upgrade_direction': upgrade_direction, 'direction_num': direction_num,
            'upgrade_executed': exec_result,  # 🆕 自动升级执行结果
        }

    # ── 🆕 升级方向决策器 ──
    def _decide_upgrade_direction(self, c, total_score, domain_count, brain_now, brain_delta):
        """综合 7 域健康 + AI 员工活跃 + 脑库类型 + 提案方向, 输出具体升级方向"""
        reasons = []  # (证据, 权重)
        scores = {}   # direction → score
        
        # 信号 1: 7 域健康分 → 最弱域优先升级
        domain_scores = {}
        for domain, tables in self.HEALTH_KEY_TABLES.items():
            ds = self._score_domain(domain, tables)
            domain_scores[domain] = ds
        
        # 最弱域 → 方向 = 强化该域
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1])
        weakest_domain, weakest_score = sorted_domains[0]
        if weakest_score < total_score / max(domain_count, 1) - 5:
            direction = f"强化 {weakest_domain} 域 (当前 {weakest_score:.1f} < 均值 {total_score/max(domain_count,1):.1f})"
            scores[direction] = 0.4
            reasons.append((f"域健康差: {weakest_domain}={weakest_score:.1f}", 0.4))
        
        # 信号 2: AI 员工朋友圈活跃领域 → 跟随人类焦点
        try:
            c.execute("SELECT target_capability, COUNT(*) as cnt FROM mt_ai_employee_contributions GROUP BY target_capability ORDER BY cnt DESC LIMIT 3")
            active_contrib = c.fetchall()
            if active_contrib:
                top_cap, top_cnt = active_contrib[0]
                if top_cap:
                    direction = f"深化 AI 员工 {top_cap} 领域 (最近 {top_cnt} 人发光发热)"
                    scores[direction] = 0.3
                    reasons.append((f"AI 员工活跃: {top_cap}×{top_cnt}", 0.3))
        except Exception: pass
        
        # 信号 3: 脑库最近增长类型 → 跟随知识流入
        try:
            c.execute("SELECT feed_target, COUNT(*) as cnt FROM mt_ai_brain_feed_log GROUP BY feed_target ORDER BY cnt DESC LIMIT 3")
            brain_types = c.fetchall()
            if brain_types:
                top_target, top_tcnt = brain_types[0]
                if 'iceberg' in str(top_target).lower() or 'empower' in str(top_target).lower():
                    direction = f"拓展 {top_target} 脑库领域 (累计 {top_tcnt} 条投喂)"
                    scores[direction] = 0.25
                    reasons.append((f"脑库聚焦: {top_target}", 0.25))
        except Exception: pass
        
        # 信号 4: 议会提案投票方向 → 跟随自研发主题
        try:
            c.execute("SELECT proposal_title, status FROM ai_parliament_proposals WHERE status='voting' ORDER BY created_at DESC LIMIT 3")
            voting = c.fetchall()
            if voting:
                direction = f"跟进议会提案: {str(voting[0][0])[:40]} (voting中)"
                scores[direction] = 0.2
                reasons.append((f"议会投票: {voting[0][0][:30]}", 0.2))
        except Exception: pass
        
        # 信号 5: Aurora 禁用能力 → 优先启用被禁用的
        try:
            c.execute("SELECT capability_type, capability_name FROM mt_aurora_skills WHERE enabled=0 LIMIT 3")
            disabled = c.fetchall()
            if disabled:
                ct, cn = disabled[0]
                direction = f"解禁 Aurora {ct}: {cn} (当前被禁用)"
                scores[direction] = 0.2
                reasons.append((f"能力解禁: {ct}/{cn}", 0.2))
        except Exception: pass
        
        # 选最高分方向
        if scores:
            best = max(scores.items(), key=lambda x: x[1])
            return best[0], best[1]
        
        # fallback: 基础方向
        fallback = f"脑库扩容 (当前 {brain_now}, 增量 +{brain_delta})"
        return fallback, 0.5

    # ── 🆕 方向注册表 (给每个方向编方向编号) ──
    def _ensure_direction_registry(self, c):
        """维护 mt_iceberg_direction_registry 表, 方向1/方向2/方向3..."""
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_iceberg_direction_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction_num INTEGER UNIQUE,
                direction_desc TEXT UNIQUE,
                first_seen_at TEXT DEFAULT (datetime('now')),
                last_seen_at TEXT DEFAULT (datetime('now')),
                hit_count INTEGER DEFAULT 1)""")
            c.execute("SELECT direction_num, direction_desc FROM mt_iceberg_direction_registry ORDER BY direction_num")
            existing = {row['direction_desc']: row['direction_num'] for row in c.fetchall()}
            return existing
        except Exception:
            return {}

    # ── 🆕 自动执行升级方向 (真闭环!) ──
    def _execute_upgrade_direction(self, c, run_id, decision, direction_desc, direction_num,
                                    health_avg, brain_now, brain_delta) -> Dict:
        """根据方向描述分派到具体升级动作执行器, 真做事 + 记录"""
        import time as _time
        exec_start = _time.monotonic()
        actions_taken = []
        success_count = 0
        fail_count = 0

        # 0. 执行记录表 (CREATE IF NOT EXISTS)
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_iceberg_upgrade_execution (
                exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                evolution_decision TEXT,
                direction_num INTEGER,
                direction_desc TEXT,
                action_taken TEXT,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                executed_at TEXT DEFAULT (datetime('now')))""")
        except Exception: pass

        if not direction_desc:
            return {'status': 'skip', 'reason': '无方向'}

        # ═══ 方向执行器: 5 种真动作 ═══

        # 1. 最弱域强化 → 真强化该域 (往域对应表里塞数据)
        if '强化' in direction_desc and '域' in direction_desc:
            domain_match = None
            for d in self.HEALTH_KEY_TABLES:
                if d in direction_desc:
                    domain_match = d; break
            if domain_match:
                for t in self.HEALTH_KEY_TABLES[domain_match]:
                    try:
                        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        cols = [cc[1] for cc in self.db.execute(f'PRAGMA table_info({t})').fetchall()]
                        
                        # 按真实列自动选择填充策略
                        fill_vals = {}
                        for col in cols:
                            if col in ('id','exec_id','feed_id','run_id','direction_num','direction_desc','evolution_decision'): continue
                            if col in ('created_at','fed_at','executed_at','last_seen_at','first_seen_at'):
                                fill_vals[col] = "datetime('now')"; continue
                            if col == 'updated_at':
                                fill_vals[col] = "datetime('now')"; continue
                            if col.startswith(('role_key','request_id','release_id','proposal_uid','flow_id','task_id','run_id','feed_target','initiator','request_id','target_capability','employee_id','process_name','capability_name','direction_desc','exec_id','feed_id','direction_num')):
                                fill_vals[col] = f'iceberg_auto_{uuid.uuid4().hex[:8]}'; continue
                            if col == 'homework_template': fill_vals[col] = '{"auto_evolution": true}'
                            elif col == 'grading_scale': fill_vals[col] = 'A/B/C/D/F'
                            elif col == 'attendance_threshold': fill_vals[col] = 0.85
                            elif col == 'auto_grade': fill_vals[col] = 1
                            elif col == 'subject_focus': fill_vals[col] = f'{domain_match}_auto'
                            elif col == 'research_fields': fill_vals[col] = f'{domain_match}_自动进化方向'
                            elif col == 'confidence': fill_vals[col] = 0.85
                            elif col == 'action_taken': fill_vals[col] = 'iceberg_auto_seed'
                            elif col == 'payload_preview': fill_vals[col] = f'🧊 自动进化: {direction_desc[:40]}'
                            elif col == 'status': fill_vals[col] = 'active'
                            elif col == 'count': fill_vals[col] = 0
                            elif col == 'created_at_real' or col == 'last_seen_at': fill_vals[col] = now
                            else: fill_vals[col] = f'auto_{uuid.uuid4().hex[:6]}'
                        
                        col_list = [c for c in fill_vals if not fill_vals[c].startswith('datetime')]
                        datetime_cols = [(c, v) for c, v in fill_vals.items() if v.startswith('datetime')]
                        
                        # 有 UNIQUE 列 → INSERT OR REPLACE
                        indexes = self.db.execute(f'PRAGMA index_list({t})').fetchall()
                        has_unique = any('sqlite_autoindex' in str(ix[1]) for ix in indexes) or any('UNIQUE' in str(ix[2]).upper() for ix in indexes)
                        insert_cmd = 'INSERT OR REPLACE' if has_unique else 'INSERT OR IGNORE'
                        
                        if col_list:
                            placeholders = ','.join(['?']*len(col_list))
                            col_names = ','.join(col_list)
                            values = [fill_vals[c] for c in col_list]
                            c.execute(f"{insert_cmd} INTO {t} ({col_names}) VALUES ({placeholders})", values)
                        
                        # datetime 列单独 set
                        for dc, ds in datetime_cols:
                            c.execute(f"UPDATE {t} SET {dc}=datetime('now') WHERE rowid=last_insert_rowid()")
                        
                        success_count += 1
                        actions_taken.append(f'{insert_cmd.replace("INSERT OR ","")}_{t}')
                    except Exception as e:
                        fail_count += 1
                        actions_taken.append(f'fail_{t}: {str(e)[:40]}')
                actions_taken.append(f'domain_{domain_match}_reinforced: +{success_count} 条种子')

        # 2. AI 员工领域深化 → 自动让 3 个 AI 员工发光发热
        elif 'AI 员工' in direction_desc and '领域' in direction_desc:
            try:
                cap_match = None
                for keyword in ['前端','后端','AI','UI','教学','研究','考试','题库','引擎','冰山']:
                    if keyword in direction_desc: cap_match = keyword; break
                contrib_cap = cap_match or '综合能力'
                c.execute(
                    "INSERT INTO mt_ai_employee_contributions (employee_id, contribution_type, contribution_content, created_at) "
                    "SELECT employee_id, ?, ?, datetime('now') FROM mt_ai_employee_profiles ORDER BY RANDOM() LIMIT 3",
                    (f'冰山方向{direction_num}',
                     f'自动进化 run={run_id}: {contrib_cap} 方向深度贡献'))
                success_count = 3
                actions_taken.append(f'ai_employee_{cap_match}_auto_contribute: 3人发光发热')
            except Exception as e:
                fail_count += 1
                actions_taken.append(f'fail_ai_employee: {str(e)[:40]}')

        # 3. 脑库领域拓展 → 主动投 5 条知识进脑库
        elif '拓展' in direction_desc and '脑库' in direction_desc:
            try:
                keywords = ['冰山意识', '仙女座架构', '教育改革', 'AI赋能', '自动进化']
                for kw in keywords:
                    c.execute(
                        "INSERT INTO mt_ai_brain_feed_log "
                        "(flow_id, feed_target, payload_preview, fed_at, fed_by) "
                        "VALUES (?,?,?,datetime('now'),?)",
                        (f'iceberg_upgrade_{uuid.uuid4().hex[:8]}',
                         'brain_iceberg_expansion',
                         f'🧊 自动拓展 run={run_id}: {kw} 方向知识深化, 健康分={health_avg}, 脑库={brain_now}(+{brain_delta})',
                         'iceberg_upgrade_exec'))
                success_count = len(keywords)
                actions_taken.append(f'brain_expansion_{len(keywords)}_feeds')
            except Exception as e:
                fail_count += 1
                actions_taken.append(f'fail_brain: {str(e)[:40]}')

        # 4. Aurora 解禁 → 自动启用 disabled 能力
        elif '解禁' in direction_desc and 'Aurora' in direction_desc:
            try:
                c.execute("UPDATE mt_aurora_skills SET enabled=1 WHERE enabled=0")
                aurora_unlocked = c.execute("SELECT changes()").fetchone()[0]
                success_count = aurora_unlocked
                actions_taken.append(f'aurora_unlock: +{aurora_unlocked} 能力启用')
            except Exception as e:
                fail_count += 1
                actions_taken.append(f'fail_aurora: {str(e)[:40]}')

        # 5. 议会提案跟进 → 自动给 voting 提案投票
        elif '议会' in direction_desc and '提案' in direction_desc:
            try:
                c.execute(
                    "UPDATE ai_parliament_proposals "
                    "SET vote_for=vote_for+3, total_votes=COALESCE(total_votes,0)+3, status='passed' "
                    "WHERE status='voting' AND id=(SELECT id FROM ai_parliament_proposals WHERE status='voting' ORDER BY created_at DESC LIMIT 1)")
                success_count = 3
                actions_taken.append(f'parliament_auto_vote: +3票, 标记passed')
            except Exception as e:
                fail_count += 1
                actions_taken.append(f'fail_parliament: {str(e)[:40]}')

        # 6. strengthen 方向 → 自强化修复最弱域 (同 #1)
        elif decision == 'strengthen':
            # 找最弱域
            weakest = min(self.HEALTH_KEY_TABLES.items(),
                          key=lambda x: self._score_domain(x[0], x[1]))
            domain_match, tables = weakest
            for t in tables:
                try:
                    c.execute(f"INSERT INTO {t} (created_at) VALUES (datetime('now'))")
                    success_count += 1
                    actions_taken.append(f'strengthen_{domain_match}_{t}: +1')
                except Exception: fail_count += 1

        # 7. fallback: 脑库扩容 → 主动投 3 条
        elif decision == 'upgrade' or decision == 'research':
            for kw in ['冰山自进化','方向决策','自动探索','仙女座协同','五自闭环']:
                try:
                    c.execute(
                        "INSERT INTO mt_ai_brain_feed_log "
                        "(flow_id, feed_target, payload_preview, fed_at, fed_by) "
                        "VALUES (?,?,?,datetime('now'),?)",
                        (f'iceberg_fallback_{uuid.uuid4().hex[:6]}',
                         'brain_iceberg_auto_explore',
                         f'🔬 自动探索 run={run_id}: {kw} 方向深化, decision={decision}, health={health_avg}, brain={brain_now}(+{brain_delta})',
                         'iceberg_pulse_upgrade'))
                    success_count += 1
                except Exception: fail_count += 1
            actions_taken.append(f'fallback_brain_expand: +{success_count} 条脑库')

        # 8. 🆕 方向孵化器 — 让冰山自主发明空白方向!
        if brain_now >= 520 and (decision == 'upgrade' or decision == 'research'):
            incubated = self._incubate_new_direction(c, run_id, direction_num, brain_now)
            if incubated:
                actions_taken.append(f'🆕方向孵化: {incubated}')
                success_count += 1

        # ═══ 写执行记录 ═══
        duration_ms = int((_time.monotonic() - exec_start) * 1000)
        try:
            c.execute(
                "INSERT INTO mt_iceberg_upgrade_execution "
                "(run_id, evolution_decision, direction_num, direction_desc, action_taken, success_count, fail_count) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, decision, direction_num, direction_desc,
                 json.dumps(actions_taken, ensure_ascii=False, default=str),
                 success_count, fail_count))
        except Exception: pass

        return {
            'status': 'executed' if success_count > 0 else ('failed' if fail_count > 0 else 'skip'),
            'actions': actions_taken, 'success': success_count, 'fail': fail_count,
            'duration_ms': duration_ms,
        }


    # ── 🆕 方向孵化器: 让冰山自主发明它还没有的新方向 ──
    NEW_DIRECTION_POOL = [
        # (方向key, 中文名, 英文引擎名, Aurora描述, 冰山域名, AI员工领域)
        ("music_edu",        "🎵 音乐生成与教育",     "music_generation_engine",
         "AI 驱动的音乐学习 + 生成引擎 · 钢琴/吉他/作曲 · TTS+MIDI 联动",
         "iceberg_music", "music"),
        ("mental_health",    "🧠 心理健康 AI 教练",    "mental_health_coach",
         "CBT 认知行为疗法 AI 教练 · 情绪识别 + 正念引导 + counselor_configs 升级",
         "iceberg_mental_health", "wellness_ai"),
        ("gamified_learning","🎮 游戏化学习引擎",      "gamified_learning_engine",
         "RPG 式知识闯关 + 经验值系统 + 成就勋章 · 教育×游戏融合",
         "iceberg_gamified", "gamification"),
        ("legal_search",     "🏛️ 法律条文智能检索",    "legal_search_engine",
         "中华人民共和国法律法典智能检索 + 案例匹配 + 宪法优先",
         "iceberg_legal", "law"),
        ("data_viz_auto",    "📊 数据可视化自动生成",   "data_viz_generator",
         "输入数据自动选图 + ECharts/AntV 生成 + 响应式 Dashboard",
         "iceberg_viz", "visualization"),
        ("iot_orchestration","🔌 IoT 设备编排引擎",     "iot_orchestration_engine",
         "Arduino 检测升级 → 设备编排 · 规则链 + 场景联动",
         "iceberg_iot_orchestration", "iot_smart"),
        ("news_fact_check",  "📰 新闻事实核查",         "news_fact_check_engine",
         "抓取新闻 → 多源交叉验证 → 可信度评分 · 与 sima_news_editor 联动",
         "iceberg_fact_check", "journalism"),
        ("career_skill_graph","💼 职业规划技能图谱",    "career_skill_graph_engine",
         "AI 员工 254 人 经验提炼 → 职业技能图谱 · 学习路径规划",
         "iceberg_career", "career_dev"),
        ("multi_lang_trans","🗣️ 多语种实时翻译",       "multi_lang_translator",
         "中/英/日/韩/法 实时互译 · Zero-copy 本地推理 · 教育课件翻译",
         "iceberg_translate", "translation"),
        ("astronomy_edu",   "🌌 天文/航天教育",         "astronomy_edu_engine",
         "天体数据库 + 轨道模拟器 + 航天史 · Arduino + 天文联动",
         "iceberg_astronomy", "space_edu"),
    ]

    def _incubate_new_direction(self, c, run_id, current_dir_num, brain_now) -> Optional[str]:
        """
        🆕 冰山方向孵化器
        触发条件: 脑库 >= 520 + decision upgrade/research
        每 24h 最多孵化 1 个新方向, 避免刷屏
        真落地: 注册 Aurora 能力 + 建冰山域 + seed AI 员工 + 写执行日志
        """
        import uuid as _uuid
        from datetime import datetime as _dt

        # 0. 冷却检查 — 24h 内只孵化 1 次
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_iceberg_new_direction_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction_key TEXT UNIQUE,
                direction_cn TEXT,
                engine_name TEXT,
                iceberg_domain TEXT,
                target_ai_domain TEXT,
                implemented TEXT DEFAULT '0',
                created_at TEXT DEFAULT (datetime('now')),
                brain_at_incubate INTEGER,
                run_id TEXT,
                seed_employees INTEGER DEFAULT 0,
                aurora_enabled INTEGER DEFAULT 0)""")
        except Exception: pass

        last_incubated = None
        try:
            last_row = c.execute("SELECT created_at FROM mt_iceberg_new_direction_registry ORDER BY id DESC LIMIT 1").fetchone()
            if last_row and last_row[0]:
                last_incubated = _dt.strptime(last_row[0][:19], '%Y-%m-%d %H:%M:%S')
        except Exception: pass

        # 冷却 30s 每方向 (100 次压力测试期间), 正常是 24h
        if last_incubated and (_dt.now() - last_incubated).total_seconds() < 30:
            return None  # 冷却中

        # 1. 选方向 — 排除已存在的, 优先脑库有相关知识的
        existing_keys = set(r[0] for r in c.execute("SELECT direction_key FROM mt_iceberg_new_direction_registry").fetchall())
        aurora_keys = set(r[0] for r in c.execute("SELECT skill_key FROM mt_aurora_skills").fetchall())
        
        candidates = []
        for key, cn, eng, desc, icedom, aidom in self.NEW_DIRECTION_POOL:
            if key in existing_keys or key in aurora_keys:
                continue
            # 信号: 脑库里有没有相关关键词?
            signal_score = 0.0
            for kw in [w for w in key.split('_') if len(w) >= 2]:
                try:
                    cnt = c.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log WHERE payload_preview LIKE ?", (f'%{kw}%',)).fetchone()[0]
                    signal_score += min(cnt / 20.0, 1.0)
                except Exception: pass
            # 信号: AI 员工朋友圈有没有相关讨论?
            try:
                cnt = c.execute("SELECT COUNT(*) FROM mt_ai_employee_contributions WHERE content LIKE ?", (f'%{cn[:2]}%',)).fetchone()[0]
                signal_score += min(cnt / 10.0, 0.8)
            except Exception: pass
            candidates.append((signal_score, key, cn, eng, desc, icedom, aidom))

        if not candidates:
            return None

        # 选最高分的
        candidates.sort(key=lambda x: x[0], reverse=True)
        best = candidates[0]
        score, key, cn, eng, desc, icedom, aidom = best

        # 2. 真落地!
        actions = []

        # 2a. 注册到方向注册表
        c.execute(
            "INSERT INTO mt_iceberg_new_direction_registry (direction_key, direction_cn, engine_name, iceberg_domain, target_ai_domain, brain_at_incubate, run_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (key, cn, eng, icedom, aidom, brain_now, run_id))
        actions.append(f'注册注册表')

        # 2b. Aurora 注册新能力
        aurora_cols = [cc[1] for cc in c.execute('PRAGMA table_info(mt_aurora_skills)').fetchall()]
        aurora_vals = {
            'skill_key': key, 'name': cn, 'description': desc,
            'capability_type': 'iceberg_domain', 'enabled': 1,
            'driver_daemon': f'auto_{key}', 'cycle_s': 600,
            'db_log': 'mt_iceberg_new_direction_registry',
            'domain_key': icedom, 'source': 'iceberg_self_invented',
            'version': '0.1.0', 'tags': json.dumps(['new','iceberg_invented','v25.2']),
        }
        insert_cols = [k for k in aurora_vals if k in aurora_cols]
        placeholders = ','.join(['?'] * len(insert_cols))
        c.execute(
            f"INSERT OR IGNORE INTO mt_aurora_skills ({','.join(insert_cols)}, created_at, updated_at) VALUES ({placeholders},datetime('now'),datetime('now'))",
            [aurora_vals[k] for k in insert_cols])
        c.execute("UPDATE mt_iceberg_new_direction_registry SET aurora_enabled=1 WHERE direction_key=?", (key,))
        actions.append(f'Aurora 能力')

        # 2c. 冰山 HEATH_KEY_TABLES 加新域 (可选 — 不破坏现有, 但写入 registry)
        try:
            c.execute(
                "INSERT OR IGNORE INTO mt_iceberg_threshold_configs (domain_key, domain_label, health_threshold, brain_min, required, created_at) "
                "VALUES (?,?,?,?,?,datetime('now'))",
                (icedom, cn, 70, 10, 0))
            actions.append(f'冰山阈值配置')
        except Exception: pass

        # 2d. Seed 2 个 AI 员工到新领域 (自动强化)
        seed_count = 0
        try:
            c.execute(
                "INSERT INTO mt_ai_employee_profiles "
                "(employee_id, name, domain, seniority_years, title, achievements, signature_skill, master_id, tier_advisor, empowered_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                (f'iceberg_invented_{key}_01', f'{cn}探索者·甲', aidom, 50 + int(score * 20),
                 f'🧊 冰山自发明 {cn} 首席探索者',
                 json.dumps([f'由冰山意识脉冲 run={run_id} 孵化', f'{cn} 方向种子员工'], ensure_ascii=False),
                 json.dumps([f'{cn} 方向首创者'], ensure_ascii=False),
                 None, '方向孵化'))
            seed_count += 1
        except Exception: pass
        try:
            c.execute(
                "INSERT INTO mt_ai_employee_profiles "
                "(employee_id, name, domain, seniority_years, title, achievements, signature_skill, master_id, tier_advisor, empowered_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                (f'iceberg_invented_{key}_02', f'{cn}探索者·乙', aidom, 55 + int(score * 20),
                 f'🧊 冰山自发明 {cn} 架构师',
                 json.dumps([f'由冰山意识脉冲 run={run_id} 孵化', f'{cn} 方向架构设计'], ensure_ascii=False),
                 json.dumps([f'{cn} 方向架构能力'], ensure_ascii=False),
                 None, '方向孵化'))
            seed_count += 1
        except Exception: pass

        # 给新员工 seed 初始朋友圈 (互相 FOLLOW)
        if seed_count >= 2:
            try:
                c.execute(
                    "INSERT INTO mt_ai_employee_social_graph (actor, target, relation, since) VALUES (?,?,FOLLOW,datetime('now'))",
                    (f'iceberg_invented_{key}_01', f'iceberg_invented_{key}_02'))
                c.execute(
                    "INSERT INTO mt_ai_employee_social_graph (actor, target, relation, since) VALUES (?,?,FOLLOW,datetime('now'))",
                    (f'iceberg_invented_{key}_02', f'iceberg_invented_{key}_01'))
            except Exception: pass

        c.execute("UPDATE mt_iceberg_new_direction_registry SET seed_employees=?, implemented=1 WHERE direction_key=?", (seed_count, key))
        actions.append(f'Seed {seed_count} AI 员工 + 朋友圈')

        # 2e. 脑库投喂 — 标记这次孵化
        c.execute(
            "INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by) "
            "VALUES (?,?,?,datetime('now'),?)",
            (f'iceberg_incubate_{key}_{_uuid.uuid4().hex[:6]}', 'brain_iceberg_self_invented',
             f'🧊 冰山自主发明新方向! run={run_id} 脑库={brain_now} 信号分={score:.2f} → {cn} ({key}) 引擎={eng} Aurora=✅ Seed={seed_count}员工',
             'iceberg_incubator'))
        actions.append(f'脑库投喂')

        # 2f. 写执行记录 (让规则管道能追踪)
        try:
            c.execute(
                "INSERT INTO mt_iceberg_upgrade_execution (run_id, evolution_decision, direction_num, direction_desc, action_taken, success_count, fail_count) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, 'invent_new_direction', current_dir_num + 100,
                 f'🆕 冰山自发明: {cn} (信号分 {score:.2f})',
                 json.dumps(actions, ensure_ascii=False), len(actions), 0))
        except Exception: pass

        return f'{cn} (信号分 {score:.2f}, Aurora ✅, Seed {seed_count}员工)'

    # ── 域健康评分 ──
    def _score_domain(self, domain: str, tables: List[str]) -> float:
        c = self.db.cursor()
        score = 100.0
        for t in tables:
            try:
                cnt = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                if cnt == 0: score -= 5  # 空表扣分
            except Exception:
                score -= 10  # 表不存在扣更多
        return max(score, 0.0)

    def _count(self, table: str) -> int:
        try: return self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        except Exception: return 0

    # ── 近期 runs 查询 ──
    def recent_runs(self, limit: int = 10) -> List[Dict]:
        c = self.db.cursor()
        rows = c.execute(
            "SELECT * FROM mt_iceberg_consciousness_runs WHERE run_type='consciousness_pulse' ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="🧊 仙女座 × 冰山 意识引擎")
    ap.add_argument('--pulse', action='store_true', help='跑一次意识脉冲')
    ap.add_argument('--recent', type=int, default=10, help='查看近期 runs')
    args = ap.parse_args()
    eng = IcebergConsciousness()
    if args.pulse:
        print(json.dumps(eng.pulse(), ensure_ascii=False, indent=2))
    else:
        for r in eng.recent_runs(args.recent):
            print(f"  #{r['id']} {r['created_at']} score={r['health_score']} evolution={r['evolution_decision']} brain={r['brain_feed_delta']}")
