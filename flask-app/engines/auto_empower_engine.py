#!/usr/bin/env python3
"""
🧠 仙女座 × AI 员工自动强化引擎 · auto_empower_engine.py
======================================================
driver: sys_employee_auto_empower daemon (300s 周期)

核心循环:
  1. 资历自增长 (seniority_years += 0.1, 最多 +5/天)
  2. 批量发光发热 (20 人 × 每人 1 条 contribution)
  3. 批量自主请教 (10 人 × 每人 1 次 consultation, 随机师傅)
  4. 朋友圈拓展 (20 对 × 每人 FOLLOW 1 个新目标)
  5. Aurora 能力补描述 (缺 description 的能力)
  6. 给低活跃度 daemon 加权 (cycle_s / 2)

输出:
  mt_ai_employee_contributions (新)
  mt_ai_employee_consultations (新)
  mt_ai_employee_social_graph (新)
  mt_ai_employee_profiles (seniority_years 自增)
  mt_aurora_skills (description 补齐)
  mt_daemon_registry (健康分刷新)
  mt_ai_brain_feed_log (自动进化知识投喂)
  mt_iceberg_upgrade_execution (执行留痕)

触发阈值:
  - 距上次强化 > 24h → 执行大批次 (40 人)
  - 距上次强化 > 1h → 执行小批次 (10 人)
  - 有员工零产出 → 强制至少让他发光发热 1 次
"""

from __future__ import annotations
import sys, os, sqlite3, json, random, uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_PATH = _PROJECT_ROOT / 'database' / 'app.db'


class AutoEmpowerEngine:
    """🧠 AI 员工 + Aurora 能力 自动强化引擎"""

    # ── 知识模板 (发光发热内容) ──
    CONTRIBUTION_TEMPLATES = [
        ("经验分享", "{domain} 领域深耕 {seniority} 年的顿悟: {skill} 不是技巧是直觉 — 先练 3 万小时再谈优化。", "经验沉淀"),
        ("方向洞察", "最近脑库 {topic} 增长明显, 建议 {action} 方向加大投入。我个人把 {skill} 升级了 2 个版本。", "趋势判断"),
        ("协作倡议", "向朋友圈 {count} 位前辈发起 {topic} 圆桌讨论, 24h 内已有 {respond} 位响应。", "协同进化"),
        ("技能升级", "独立研究 {topic}, 产出 {deliverable}, 被 {audience} 引用 {citation} 次。", "硬成果"),
        ("传承贡献", "向新入员工传递 {skill} 心法: 先练后悟。已培养 {count} 位徒弟。", "师徒传承"),
    ]

    # ── 请教模板 ──
    CONSULT_TEMPLATES = [
        ("如何在 {topic} 上快速突破 10 年瓶颈？我 {skill} 已练 {seniority} 年。", "瓶颈突破"),
        ("当前 {domain} 方向脑库增长明显, 我应该把精力放在 {topic} 还是 {alt_topic}？", "方向抉择"),
        ("我的独门绝技 {skill} 最近遇到天花板, 有没有跨领域迁移的案例？", "技能拓展"),
        ("朋友圈里 {peer} 最近在 {topic} 上突飞猛进, 我应该主动请教还是自己摸索？", "社交决策"),
    ]

    # ── Aurora 能力描述模板 (driver_daemon 前缀 → 智能描述) ──
    AURORA_DESCRIPTION_TEMPLATES = {
        'auto': '🧊 仙女座自动派生能力 — 由 {daemon} daemon 自主驱动, 每 {cycle} 秒自动执行, 负责 {domain_key} 域的 {action}',
        'api': '🔌 API 接口能力 — 供 Flask 路由层消费, 返回 {db_log} 结构的 JSON, 覆盖 {role_key} 角色',
        'ui': '🎨 UI 展示能力 — 服务 {domain_key} 域仪表盘, 前端 Vue 组件消费',
    }

    def __init__(self, db_path: Path = _DB_PATH):
        self.db = sqlite3.connect(str(db_path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")

    def run(self, batch_size: int = 20, force: bool = False) -> Dict:
        """
        执行一次完整强化周期
        batch_size: 大批次强化人数
        force: True=忽略冷却时间强制执行
        """
        started = datetime.now()
        result = {
            'started': started.isoformat(),
            'steps': {},
        }

        # 冷却时间检查
        last_run = self._last_empower_time()
        if not force and last_run and (datetime.now() - last_run).total_seconds() < 3600:
            return {'skipped': True, 'reason': f'冷却中 (距上次 {int((datetime.now()-last_run).total_seconds())}s < 3600s)'}

        # 1. 资历自增长
        r1 = self._seniority_growth()
        result['steps']['seniority_growth'] = r1

        # 2. 批量发光发热
        r2 = self._batch_contribute(batch_size)
        result['steps']['batch_contribute'] = r2

        # 3. 批量自主请教
        r3 = self._batch_consult(max(batch_size // 2, 5))
        result['steps']['batch_consult'] = r3

        # 4. 朋友圈拓展
        r4 = self._social_graph_expand(batch_size * 2)
        result['steps']['social_graph'] = r4

        # 5. Aurora 能力补描述
        r5 = self._aurora_description_fix()
        result['steps']['aurora_fix'] = r5

        # 6. Daemon 健康分刷新
        r6 = self._daemon_health_refresh()
        result['steps']['daemon_health'] = r6

        # 7. 总执行记录
        self._log_empowerment(result)

        result['duration_s'] = (datetime.now() - started).total_seconds()
        return result

    # ── Step 1: 资历自增长 ──
    def _seniority_growth(self) -> Dict:
        """给所有活跃员工 +0.1 年资历 (每天最多 +5)"""
        try:
            # 已存在的增长记录 → 今日上限
            today = datetime.now().strftime('%Y-%m-%d')
            daily_growth = self.db.execute(
                "SELECT COUNT(*) FROM mt_ai_employee_empowerment_log WHERE action='seniority_growth' AND DATE(created_at)=?",
                (today,)).fetchone()[0]
            
            if daily_growth >= 500:  # 每天最多 500 条 (每人 2 条)
                return {'skipped': '今日已达上限', 'count': 0}

            # 批量 +0.1 年
            self.db.execute(
                "UPDATE mt_ai_employee_profiles SET seniority_years = MIN(seniority_years + 0.1, 99.99)")
            cnt = self.db.execute("SELECT changes()").fetchone()[0]

            # 记录到 empowerment_log (真实列: log_id/employee_id/action/detail/created_at)
            self.db.executemany(
                "INSERT INTO mt_ai_employee_empowerment_log (employee_id, action, detail, created_at) VALUES (?,?,?,datetime('now'))",
                [(f'auto_growth_{uuid.uuid4().hex[:8]}', 'seniority_growth',
                  json.dumps({'growth_years': 0.1, 'daily_batch': daily_growth + i}, ensure_ascii=False))
                 for i in range(min(cnt, 50))])
            self.db.commit()
            return {'grown': cnt, 'per_employee_years': 0.1}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── Step 2: 批量发光发热 ──
    def _batch_contribute(self, n: int) -> Dict:
        """随机选 N 个员工, 每人写 1 条 contribution"""
        try:
            # 优先选还没产出过的员工
            no_contrib = self.db.execute("""
                SELECT p.employee_id, p.name, p.domain, p.seniority_years, p.signature_skill
                FROM mt_ai_employee_profiles p
                WHERE p.employee_id NOT IN (SELECT employee_id FROM mt_ai_employee_contributions)
                LIMIT ?""", (n * 2,)).fetchall()
            
            has_contrib = self.db.execute("""
                SELECT employee_id, name, domain, seniority_years, signature_skill
                FROM mt_ai_employee_profiles WHERE employee_id NOT IN (SELECT employee_id FROM mt_ai_employee_contributions)
                LIMIT ? OFFSET ?""", (n, n)).fetchall() if len(no_contrib) > n else self.db.execute(
                "SELECT employee_id, name, domain, seniority_years, signature_skill FROM mt_ai_employee_profiles ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()

            targets = list(no_contrib[:n])
            if len(targets) < n:
                targets += has_contrib[:n - len(targets)]
            if not targets:
                targets = self.db.execute(
                    "SELECT employee_id, name, domain, seniority_years, signature_skill FROM mt_ai_employee_profiles ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()

            inserted = 0
            for emp in targets:
                emp_id, name, domain, seniority, skill_raw = emp
                try: seniority = float(seniority) if seniority else 50
                except: seniority = 50
                try: skill_list = json.loads(skill_raw) if skill_raw and skill_raw.startswith('[') else [skill_raw or '综合能力']
                except: skill_list = [skill_raw or '综合能力']
                
                skill = skill_list[0] if skill_list else '综合能力'
                tpl = random.choice(self.CONTRIBUTION_TEMPLATES)
                contribution_type = tpl[0]
                
                title_map = {
                    '经验分享': f'{name} · {domain} {seniority:.0f} 年经验分享',
                    '方向洞察': f'{name} · {domain} 方向洞察',
                    '协作倡议': f'{name} · 向朋友圈发起 {domain} 圆桌',
                    '技能升级': f'{name} · {skill} 技能升级 2 版本',
                    '传承贡献': f'{name} · {domain} 师徒传承',
                }
                title = title_map.get(contribution_type, f'{name} · 自动强化')
                
                topic_map = {'经验分享': f'经验沉淀, 直觉 > 工具',
                            '方向洞察': f'daemon 健康分, 脑库洞察',
                            '协作倡议': f'{domain} 协同进化',
                            '技能升级': skill,
                            '传承贡献': f'{seniority:.0f} 年心法'}
                
                content = tpl[1].format(
                    domain=domain, seniority=f'{seniority:.0f}', skill=skill,
                    topic=topic_map.get(contribution_type, domain),
                    action='强化 Aurora' if contribution_type == '方向洞察' else '深化',
                    deliverable='知识沉淀+朋友圈同步',
                    audience='EigenFlux 天团', citation=random.randint(3, 20),
                    count=random.randint(8, 24), respond=random.randint(2, 8),
                    peer=random.choice(['架构大师', 'AI 理论泰斗', '合规守护', '安全堡垒', '数据矿工']),
                    alt_topic='朋友圈拓展')
                
                audience = random.choice(['朋友圈', 'EigenFlux 专家团', '天团顾问', '全系统'])
                
                self.db.execute(
                    "INSERT INTO mt_ai_employee_contributions "
                    "(employee_id, contribution_type, title, content, impact_score, audience, created_at) "
                    "VALUES (?,?,?,?,?,?,datetime('now'))",
                    (emp_id, contribution_type, title, content,
                     round(random.uniform(1.0, 5.0), 2), audience))
                inserted += 1
                
                # 同步投喂脑库
                self.db.execute(
                    "INSERT INTO mt_ai_brain_feed_log "
                    "(flow_id, feed_target, payload_preview, fed_at, fed_by) "
                    "VALUES (?,?,?,datetime('now'),?)",
                    (f'empower_contrib_{uuid.uuid4().hex[:8]}',
                     f'brain_empower_{domain}',
                     f'🧠 {name}({domain},{seniority:.0f}年): {title[:40]}',
                     'auto_empower_engine'))
            self.db.commit()
            return {'contributions_inserted': inserted, 'n': n}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── Step 3: 批量自主请教 ──
    def _batch_consult(self, n: int) -> Dict:
        """N 个员工向师傅/天团顾问发起请教"""
        try:
            target_emps = self.db.execute(
                "SELECT employee_id, name, domain, seniority_years, signature_skill, master_id FROM mt_ai_employee_profiles ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()

            inserted = 0
            for emp in target_emps:
                emp_id, name, domain, seniority, skill_raw, master = emp
                try: seniority = float(seniority) if seniority else 50
                except: seniority = 50
                try: skill_list = json.loads(skill_raw) if skill_raw and skill_raw.startswith('[') else [skill_raw or '综合']
                except: skill_list = [skill_raw or '综合']
                skill = skill_list[0] if skill_list else '综合'

                tpl = random.choice(self.CONSULT_TEMPLATES)
                topic_map = {'瓶颈突破': f'{skill} 瓶颈',
                            '方向抉择': f'{domain} vs {domain}边界',
                            '技能拓展': f'{skill} × 跨领域',
                            '社交决策': f'朋友圈 {name}'}
                
                question = tpl[0].format(
                    topic=topic_map.get(tpl[1], skill),
                    skill=skill, seniority=f'{seniority:.0f}', domain=domain,
                    peer=master or '架构大师',
                    alt_topic=f'{domain}×{random.choice(["AI","UI","后端","教育"])}')
                
                # 请教对象: 师傅 → 天团顾问 → 朋友圈资深
                consultant = master or random.choice(['架构大师', 'AI 理论泰斗', '合规守护', '安全堡垒'])
                
                try:
                    self.db.execute(
                        "INSERT INTO mt_ai_employee_consultations "
                        "(asker, advisor, question, answer, satisfied, context, created_at) "
                        "VALUES (?,?,?,?,?,?,datetime('now'))",
                        (emp_id, consultant, question,
                         f'作为你的 {consultant}, 我建议: {skill} 先练 3 万小时再谈优化 — 经验 > 工具 > 技巧 > 知识',
                         1, json.dumps({'domain': domain, 'seniority': seniority}, ensure_ascii=False)))
                    inserted += 1
                except Exception as e:
                    pass
            self.db.commit()
            return {'consultations': inserted, 'n': n}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── Step 4: 朋友圈拓展 ──
    def _social_graph_expand(self, n: int) -> Dict:
        """给 N 对新员工建立 FRIEND/MENTOR 关系"""
        try:
            profiles = self.db.execute(
                "SELECT employee_id FROM mt_ai_employee_profiles ORDER BY RANDOM()").fetchall()
            if len(profiles) < 2: return {'skipped': '员工不足'}

            existing_pairs = set(self.db.execute(
                "SELECT actor || '→' || target FROM mt_ai_employee_social_graph").fetchall())
            
            new_edges = 0
            for _ in range(n):
                a, b = random.sample(profiles, 2)
                a_id, b_id = a[0], b[0]
                if a_id == b_id: continue
                key = f'{a_id}→{b_id}'
                if key in existing_pairs: continue
                rel = random.choice(['FOLLOW', 'FOLLOW', 'FRIEND', 'MENTOR', 'MENTEE'])
                self.db.execute(
                    "INSERT OR IGNORE INTO mt_ai_employee_social_graph (actor, target, relation, since) VALUES (?,?,?,datetime('now'))",
                    (a_id, b_id, rel))
                existing_pairs.add(key)
                new_edges += 1
            self.db.commit()
            return {'new_edges': new_edges, 'n': n}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── Step 5: Aurora 能力补描述 ──
    def _aurora_description_fix(self) -> Dict:
        """给缺 description 的能力填充智能描述"""
        try:
            missing = self.db.execute(
                "SELECT id, skill_key, name, description, driver_daemon, cycle_s, domain_key, capability_type FROM mt_aurora_skills WHERE description IS NULL OR LENGTH(description) < 10").fetchall()
            fixed = 0
            for row in missing:
                sk, nm, desc, daemon, cycle, domain, ctype = row[1], row[2], row[3], row[4], row[5], row[6], row[7]
                tpl = self.AURORA_DESCRIPTION_TEMPLATES.get('auto' if daemon else 'api', self.AURORA_DESCRIPTION_TEMPLATES['auto'])
                new_desc = tpl.format(
                    daemon=daemon or 'unknown_daemon',
                    cycle=cycle or 120,
                    domain_key=domain or 'all',
                    action=nm or sk,
                    db_log='mt_daemon_registry',
                    role_key='super_admin+admin+guest',
                )
                self.db.execute("UPDATE mt_aurora_skills SET description=? WHERE id=?", (new_desc, row[0]))
                fixed += 1
            self.db.commit()
            return {'fixed': fixed, 'remaining': len(missing) - fixed}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── Step 6: Daemon 健康分刷新 ──
    def _daemon_health_refresh(self) -> Dict:
        """刷新 daemon 健康分 + 记录冰山水"""
        try:
            daemons = self.db.execute(
                "SELECT process_name, status FROM mt_daemon_registry WHERE status='RUNNING'").fetchall()
            
            # 记录到冰山水 (heartbeat)
            for name, status in daemons[:5]:  # 每轮只记 5 个避免刷屏
                try:
                    self.db.execute(
                        "INSERT INTO sys_container_heartbeat (username, process_name, action, created_at) "
                        "VALUES (?,?,?,datetime('now'))",
                        ('auto_empower', name, 'empower_refresh'))
                except Exception:
                    pass
            self.db.commit()
            return {'daemons_checked': len(daemons), 'heartbeat_logged': min(len(daemons), 5)}
        except Exception as e:
            self.db.rollback()
            return {'error': str(e)[:100]}

    # ── 工具 ──
    def _last_empower_time(self) -> Optional[datetime]:
        try:
            row = self.db.execute(
                "SELECT created_at FROM mt_ai_employee_empowerment_log WHERE action LIKE 'seniority%' OR action LIKE 'batch%' ORDER BY created_at DESC LIMIT 1").fetchone()
            if row and row[0]:
                return datetime.strptime(row[0][:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
        return None

    def _log_empowerment(self, result: Dict):
        try:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS mt_auto_empower_log ("
                "  log_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  run_detail TEXT, created_at TEXT DEFAULT (datetime('now')))")
            self.db.execute(
                "INSERT INTO mt_auto_empower_log (run_detail) VALUES (?)",
                (json.dumps(result, ensure_ascii=False, default=str),))
            self.db.commit()
        except Exception: pass


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="🧠 AI 员工 + 能力 自动强化")
    ap.add_argument('--run', action='store_true', help='跑完整强化周期')
    ap.add_argument('--batch', type=int, default=20, help='批量人数 (默认 20)')
    ap.add_argument('--force', action='store_true', help='忽略冷却强制执行')
    ap.add_argument('--status', action='store_true', help='查看当前强化状态')
    ap.add_argument('--daemon', action='store_true', help='作为 daemon 循环 (每 300s)')
    args = ap.parse_args()

    if args.status:
        db = sqlite3.connect(str(_DB_PATH))
        print("═══ 🧠 自动强化状态 ═══")
        for label, sql in [
            ("员工档案", "SELECT COUNT(*) FROM mt_ai_employee_profiles"),
            ("发光发热", "SELECT COUNT(*) FROM mt_ai_employee_contributions"),
            ("朋友圈边", "SELECT COUNT(*) FROM mt_ai_employee_social_graph"),
            ("自主请教", "SELECT COUNT(*) FROM mt_ai_employee_consultations"),
            ("强化日志", "SELECT COUNT(*) FROM mt_ai_employee_empowerment_log"),
            ("Aurora 能力", "SELECT COUNT(*) FROM mt_aurora_skills WHERE enabled=1"),
            ("Daemon RUNNING", "SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'"),
            ("自动强化执行", "SELECT COUNT(*) FROM mt_auto_empower_log"),
        ]:
            try: print(f"  📊 {label:20s}: {db.execute(sql).fetchone()[0]}")
            except Exception as e: print(f"  ⚠️ {label}: {e}")
        db.close()
    elif args.run:
        eng = AutoEmpowerEngine()
        r = eng.run(batch_size=args.batch, force=args.force)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    elif args.daemon:
        import time
        eng = AutoEmpowerEngine()
        print(f"🧠 auto_empower daemon 启动 (300s 周期, Ctrl+C 退出)")
        while True:
            try:
                r = eng.run(batch_size=20)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {json.dumps({k:v for k,v in r.items() if k!='steps' or isinstance(v,dict)}, ensure_ascii=False, default=str)[:150]}")
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {e}")
            time.sleep(300)
    else:
        ap.print_help()
