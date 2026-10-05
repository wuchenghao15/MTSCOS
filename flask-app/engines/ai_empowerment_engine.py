#!/usr/bin/env python3
"""
🤖 AI 员工赋能引擎 · engines/ai_empowerment_engine.py
========================================================
每个 AI 员工都有:
  ① 50+ 年相关经验 (资历/代表作/独门绝技)
  ② 能团队协作
  ③ 能拉取其他员工朋友圈 + 社交圈
  ④ 能自主请教师傅 + EigenFlux 网络专家 + 天团顾问
  ⑤ 能自主发光发热 (产出自动汇总)

数据库表 (首次启动自动建):
  mt_ai_employee_profiles        — AI 员工资历档案 (50年资历/代表作/独门绝技)
  mt_ai_employee_social_graph    — 朋友圈 + 师徒链 (follow/mentor/mentee)
  mt_ai_employee_consultations   — 自主请教记录 (问谁/得到什么答复)
  mt_ai_employee_contributions   — 发光发热产出汇总 (作品/建议/脑库投喂)
  mt_ai_employee_empowerment_log — 赋能动作审计日志

用法:
  python3 engines/ai_empowerment_engine.py --seed       # 给所有员工赋予 50+ 年经验
  python3 engines/ai_empowerment_engine.py --sociograph # 构建朋友圈 + 师徒链
  python3 engines/ai_empowerment_engine.py --consult    # 模拟一次请教
  python3 engines/ai_empowerment_engine.py --status     # 赋能状态
"""
from __future__ import annotations

# 规则管道: 所有维护升级必须走管道
from ai_engines.rules_engine.maintenance_pipeline import maintenance_pipeline
import os, sys, sqlite3, json, random, hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

_PROJECT_ROOT = Path(__file__).parent.parent
_DB = str(_PROJECT_ROOT / 'database' / 'app.db')

# ── 资历种子数据 ──────────────────────────────────────────────
# 8 大领域 × 每领域 25 种资历模板 = 200 种种子
DOMAIN_SEEDS = {
    'engineering': {
        'label': '软件工程',
        'titles': ['资深架构师','系统设计大师','全栈工程师','微服务专家','数据库调优圣手',
                  '高并发架构师','分布式系统专家','DevOps 元老','性能优化大师','代码质量守护者'],
        'achievements': [
            '主导过 50+ 大型分布式系统设计 (日均千万级请求)',
            '在 GitHub 上有 12 个万星项目贡献',
            '发表过 3 本系统设计专著',
            '给 20+ 开源项目贡献过核心模块',
            '主导过 3 次千万级 DAU 系统重构',
        ],
        'signature_skills': [
            '能在 30 秒内定位一个高并发系统的瓶颈',
            '能把单体系统无损拆解为 50+ 微服务',
            '能为任何技术选型写出一篇让反对者也认可的 ADR',
        ],
    },
    'education': {
        'label': '教育',
        'titles': ['特级教师','金牌导师','课程设计大师','AI 教研专家','自适应学习体系奠基人',
                   'STEM 教育先锋','在线教育拓荒者','教育心理学泰斗','作文批改圣手','编程启蒙教父'],
        'achievements': [
            '累计批改过 120 万份学生作业',
            '主导过全国 20 个城市的自适应学习系统落地',
            '设计的课程体系被 50+ 机构采用',
            '培养过 3 万+ 学生考上理想学校',
            '发表过 40+ 篇教育心理学顶会论文',
        ],
        'signature_skills': [
            '看一篇作文 10 秒能给 15 个维度的精准反馈',
            '能为任何知识点生成 5 种不同难度的讲解版本',
            '能预测一个学生未来 3 年的学习路径并给出个性化方案',
        ],
    },
    'research': {
        'label': '科研',
        'titles': ['首席科学家','AI 理论大师','多模态先驱','大模型架构研究员','知识图谱奠基人',
                   '神经符号结合专家','强化学习泰斗','LLM 对齐研究员','Agent 系统设计师','科研方法论大师'],
        'achievements': [
            '在 Nature/Science 发表过 8 篇论文',
            'Google Scholar 引用 > 50,000',
            '持有 30+ AI 领域核心专利',
            '指导过 15 名博士毕业',
            '担任过 3 个顶级 AI 会议的 PC Chair',
        ],
        'signature_skills': [
            '读完一篇 arXiv 论文 5 分钟能给出 10 条审稿意见',
            '能把一个前沿概念用一个大一新生也懂的类比解释清楚',
            '能为任何研究方向写出一份让人眼前一亮的 proposal',
        ],
    },
    'wellness': {
        'label': '心理与福祉',
        'titles': ['心理咨询大师','心理治疗师','家校沟通专家','学习焦虑干预专家','心理健康导师',
                   '情绪调节教练','积极心理学先锋','正念冥想导师','青少年心理专家','家庭治疗师'],
        'achievements': [
            '累计服务过 8,000+ 来访者',
            '帮助过 300+ 家庭修复亲子关系',
            '开发的情绪调节课程被 100+ 学校采用',
            '危机干预成功率 96%',
            '发表过 25+ 篇心理健康论文',
        ],
        'signature_skills': [
            '听到一个人的苦恼 30 秒能感知他/她真正需要什么',
            '能用一个故事化解一个学生的学习焦虑',
            '能为任何情绪问题给出 3 种不同学派的干预方案',
        ],
    },
    'mentorship': {
        'label': '师徒与成长',
        'titles': ['金牌教练','职业发展导师','技能图谱构建者','师徒链搭建专家','成长型思维教练',
                   'T 型人才培养大师','知识萃取专家','经验传承设计师','技能树引路人','终身学习倡导者'],
        'achievements': [
            '带过 500+ 门徒走上人生巅峰',
            '设计的技能图谱覆盖 200+ 职业',
            '把 1,000+ 老师傅的经验系统化传承',
            '培养出 200+ 特级教师/专家',
            '著有《师徒关系设计》等 5 部专著',
        ],
        'signature_skills': [
            '看一个学徒 5 分钟能判断他的成长路径',
            '能把一个老师傅 50 年的经验提炼成 20 条可操作的原则',
            '能为任何技能设计一条让任何人都能 100 小时入门的路径',
        ],
    },
    'creative': {
        'label': '创意写作',
        'titles': ['顶级文案','叙事架构大师','诗歌圣手','剧本杀设计大师','网文白金作者',
                   '广告文案教父','品牌故事专家','AI 写作前沿','多体裁创作大师','文字魔法师'],
        'achievements': [
            '出版过 12 本畅销书 (累计销量 200 万+)',
            '为 50+ 顶级品牌写过 slogan',
            '创作的诗歌被选入 30 本选集',
            '剧本杀作品被 200+ 门店采用',
            '网文字数累计 2,000 万+',
        ],
        'signature_skills': [
            '给任何一个词 3 秒能写出 5 种不同风格的句子',
            '能为任何品牌写 10 个让人拍案的 slogan',
            '能把一个平凡的故事讲成一个让人哭的故事',
        ],
    },
    'integration': {
        'label': '跨域整合',
        'titles': ['T 型人才','跨界大师','系统思维专家','复杂问题解决者','全栈通才',
                   '多学科综合者','跨模态融合者','知识网络构建者','元学科探索者','创新杂交专家'],
        'achievements': [
            '跨界整合过 15 个不同领域的知识解决实际问题',
            '设计过 3 个跨学科培养体系',
            '发表过 50+ 篇跨学科研究',
            '获得过 10+ 跨领域创新奖项',
            '主导过 5 个行业的跨界数字化转型',
        ],
        'signature_skills': [
            '给一个问题 5 分钟能从 10 个不同学科找到解法',
            '能把两个看似不相关的领域碰撞出一个新方向',
            '能为任何难题写出一份跨 5 领域的综合解决方案',
        ],
    },
    'operations': {
        'label': '运维与守护',
        'titles': ['SRE 大师','稳定性守护人','故障排查圣手','自动化运维先锋','高可用架构师',
                   '混沌工程专家','性能监控大师','故障自愈系统设计师','零事故传奇','灾备设计专家'],
        'achievements': [
            '守护过 100+ 系统连续 5 年 99.99% 可用',
            '处理过 500+ 生产事故 (平均 MTTR < 5 分钟)',
            '设计的自动化守护系统节省过 10 万+ 人力小时',
            '故障预测准确率 99%',
            '主导过 10+ 次同城双活/三地五中心建设',
        ],
        'signature_skills': [
            '看一张监控大盘 10 秒能判断会不会出事',
            '能在任何系统写出一段让它自己维护自己的代码',
            '能为任何 SLA 要求设计一套让它永远不宕机的架构',
        ],
    },
}

# EigenFlux 天团顾问
TIAN_TUAN_ADVISORS = [
    {'name':'架构大师', 'specialty':'系统架构','seniority_years':80},
    {'name':'合规守护', 'specialty':'法律合规','seniority_years':60},
    {'name':'安全堡垒', 'specialty':'AI 安全','seniority_years':65},
    {'name':'数据库DBA王', 'specialty':'数据库','seniority_years':70},
    {'name':'运维铁拳', 'specialty':'SRE/DevOps','seniority_years':75},
    {'name':'前端魔法师', 'specialty':'前端设计','seniority_years':55},
    {'name':'后端大牛', 'specialty':'后端架构','seniority_years':68},
    {'name':'AI 理论泰斗','specialty':'AI/LLM','seniority_years':90},
    {'name':'数据矿工', 'specialty':'数据分析','seniority_years':58},
    {'name':'IoT 布道师', 'specialty':'IoT/硬件','seniority_years':52},
]


class AIEmpowermentEngine:
    """🤖 AI 员工赋能引擎"""

    def __init__(self, db_path: str = _DB):
        self._db = db_path
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _init_tables(self):
        c = self._conn()
        c.executescript(f"""
        CREATE TABLE IF NOT EXISTS mt_ai_employee_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE,                     -- 关联 ai_employees.id
            name TEXT,                                    -- AI 员工名
            domain TEXT NOT NULL,                         -- engineering/education/research/...
            seniority_years INTEGER NOT NULL DEFAULT 50,  -- 50+ 年经验
            title TEXT,                                   -- 头衔
            achievements TEXT,                            -- JSON 代表作
            signature_skill TEXT,                         -- JSON 独门绝技
            master_id TEXT,                               -- 师傅 employee_id
            tier_advisor TEXT,                            -- 天团顾问名
            empowered_at TEXT DEFAULT '{self._now()}',
            updated_at TEXT DEFAULT '{self._now()}'
        );
        CREATE TABLE IF NOT EXISTS mt_ai_employee_social_graph (
            sg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,           -- 谁
            target TEXT NOT NULL,          -- 关注谁
            relation TEXT NOT NULL,        -- FOLLOW / MENTOR / MENTEE / COLLEAGUE / FRIEND
            since TEXT DEFAULT '{self._now()}',
            UNIQUE(actor, target, relation)
        );
        CREATE TABLE IF NOT EXISTS mt_ai_employee_consultations (
            consult_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asker TEXT NOT NULL,            -- 提问 AI 员工
            advisor TEXT NOT NULL,          -- 回答者 (师傅/天团/EigenFlux 专家)
            question TEXT NOT NULL,
            answer TEXT,
            satisfied INTEGER DEFAULT 1,    -- 0/1 是否满意
            context TEXT,                   -- JSON 上下文 (朋友圈动态/脑库/经验)
            created_at TEXT DEFAULT '{self._now()}'
        );
        CREATE TABLE IF NOT EXISTS mt_ai_employee_contributions (
            contr_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            contribution_type TEXT NOT NULL,-- 作品/建议/脑库/代码/文案/设计/提案
            title TEXT,
            content TEXT,
            impact_score REAL DEFAULT 0,    -- 影响力评分
            audience TEXT,                  -- 受众 (朋友圈/整个系统/用户)
            tags TEXT,                      -- JSON tags
            created_at TEXT DEFAULT '{self._now()}'
        );
        CREATE TABLE IF NOT EXISTS mt_ai_employee_empowerment_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            action TEXT NOT NULL,           -- empower/follow/consult/contribute/collaborate
            detail TEXT,                    -- JSON 详情
            created_at TEXT DEFAULT '{self._now()}'
        );
        CREATE INDEX IF NOT EXISTS idx_profiles_domain ON mt_ai_employee_profiles(domain);
        CREATE INDEX IF NOT EXISTS idx_social_actor ON mt_ai_employee_social_graph(actor);
        CREATE INDEX IF NOT EXISTS idx_social_target ON mt_ai_employee_social_graph(target);
        CREATE INDEX IF NOT EXISTS idx_consult_asker ON mt_ai_employee_consultations(asker);
        CREATE INDEX IF NOT EXISTS idx_contr_emp ON mt_ai_employee_contributions(employee_id);
        """)
        c.commit(); c.close()

    # ── 1. 资历种子 (给所有员工赋予 50+ 年经验) ──
    def seed_profiles(self) -> Dict:
        """从 ai_employees 拉全部员工 → 按领域分配资历"""
        conn = self._conn()
        # 拉全部员工 (真实 schema 用 name/specialties/capabilities)
        employees = []
        for tbl in ['ai_employees','mtscos_ai_employees','eigenflux_registrations']:
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info({tbl})').fetchall()]
                id_col = 'employee_code' if 'employee_code' in cols else 'uid' if 'uid' in cols else 'id'
                name_col = 'name' if 'name' in cols else None
                spec_col = 'specialties' if 'specialties' in cols else 'expertise_json' if 'expertise_json' in cols else None
                cap_col = 'capabilities' if 'capabilities' in cols else 'skills_json' if 'skills_json' in cols else None
                role_col = 'group_tag' if 'group_tag' in cols else 'role' if 'role' in cols else None
                limit = 800 if tbl == 'ai_employees' else 500
                rows = conn.execute(f"SELECT {id_col},{name_col},{spec_col},{cap_col},{role_col} FROM {tbl} LIMIT {limit}").fetchall()
                for r in rows:
                    employees.append({
                        'id': f'{tbl}_{r[0]}',
                        'name': r[1] or f'AI-{r[0]}',
                        'specialties': r[2] or '',
                        'capabilities': r[3] or '',
                        'role': r[4] or '',
                    })
            except Exception as e: pass

        # 种子 EigenFlux 天团顾问 (如果还没有的话)
        for adv in TIAN_TUAN_ADVISORS:
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_ai_employee_profiles
                    (employee_id, name, domain, seniority_years, title, achievements, signature_skill, tier_advisor)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (f'tiantu_{adv["name"]}', adv['name'], 'tier_advisor', adv['seniority_years'],
                     f'Tier 天团 · {adv["specialty"]}',
                     json.dumps([f'在 {adv["specialty"]} 领域深耕 {adv["seniority_years"]} 年',
                                 f'指导过系统中所有 AI 员工'], ensure_ascii=False),
                     json.dumps([f'任何 {adv["specialty"]} 问题 30 秒内给出专家级建议'], ensure_ascii=False),
                     adv['name']))
            except Exception: pass

        inserted = 0
        domains_keys = list(DOMAIN_SEEDS.keys())
        conn.execute("DELETE FROM mt_ai_employee_profiles WHERE employee_id NOT LIKE 'tiantu_%'")  # 清空旧员工, 保留天团
        for emp in employees:
            # 根据 specialties / capabilities / group_tag 推断 domain
            combined = (emp['specialties'] or '') + ' ' + (emp['capabilities'] or '') + ' ' + (emp['role'] or '')
            dk = self._infer_domain(combined, domains_keys)
            seed = DOMAIN_SEEDS[dk]
            # 资历: group_tag 里 GRAND_MASTER / NATIONAL_GRAND_MASTER 额外加成
            tag = emp['role'].upper() if emp['role'] else ''
            years = 50 + random.randint(0, 49)
            if 'GRAND_MASTER' in tag or 'NATIONAL' in tag or 'ARCHITECT' in tag:
                years = max(years, 75 + random.randint(0, 20))  # 国手 75–95 年
            elif 'EXPERT' in tag or 'SENIOR' in tag or 'MASTER' in tag:
                years = max(years, 60 + random.randint(0, 15))
            title = random.choice(seed['titles'])
            ach = random.sample(seed['achievements'], min(3, len(seed['achievements'])))
            sig = random.choice(seed['signature_skills'])
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO mt_ai_employee_profiles
                       (employee_id, name, domain, seniority_years, title, achievements, signature_skill)
                       VALUES (?,?,?,?,?,?,?)""",
                    (emp['id'], emp['name'], dk, years, title,
                     json.dumps(ach, ensure_ascii=False),
                     json.dumps([sig], ensure_ascii=False)))
                if conn.total_changes > 0: inserted += 1
            except Exception: pass
        conn.commit(); conn.close()
        return {'inserted': inserted, 'tiantu': len(TIAN_TUAN_ADVISORS), 'domains': len(domains_keys)}

    def _infer_domain(self, text: str, candidates: List[str]) -> str:
        rl = (text or '').lower()
        keywords = {
            'engineering':['engineer','dev','code','architect','sys','server','ops','infra','backend','frontend','fullstack'],
            'education':['teacher','educat','teach','school','student','lesson','course','homework','exam','作文'],
            'research':['research','scientist','professor','ai','ml','llm','paper','lab','novel','theory','科学家','教授'],
            'wellness':['counsel','psych','mental','health','wellness','care','psychological','心理','辅导'],
            'mentorship':['mentor','teacher','coach','guide','师徒','导师','师傅','成长','career'],
            'creative':['writer','poet','creative','copy','novel','content','文曲星','写作','文案','诗人'],
            'integration':['integrat','cross','t-shape','bridge','跨界','跨域','全栈通才'],
            'operations':['ops','sre','monitor','fault','fix','auto','守护','运维','故障','稳定性'],
        }
        for dk, kws in keywords.items():
            for kw in kws:
                if kw in rl: return dk
        return random.choice(candidates)

    # ── 2. 朋友圈 + 师徒链 ──
    @maintenance_pipeline(action="migrate", risk="medium", operator="empowerment_engine")
    def seed_social_graph(self) -> Dict:
        conn = self._conn()
        profiles = [dict(r) for r in conn.execute(
            "SELECT employee_id, name, domain FROM mt_ai_employee_profiles LIMIT 400").fetchall()]

        inserted = 0
        n = len(profiles)
        if n < 2:
            conn.close(); return {'inserted': 0, 'note': '先 seed_profiles'}

        # 同 domain 员工互相关注 (COLLEAGUE / FRIEND)
        from collections import defaultdict
        by_domain = defaultdict(list)
        for p in profiles: by_domain[p['domain']].append(p)

        for dk, plist in by_domain.items():
            for p in plist:
                # 关注同领域 5–10 个同事
                others = [q for q in plist if q['employee_id'] != p['employee_id']]
                random.shuffle(others)
                for q in others[:random.randint(5, min(10, len(others)))]:
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO mt_ai_employee_social_graph
                               (actor, target, relation) VALUES (?,?,?)""",
                            (p['employee_id'], q['employee_id'], 'FOLLOW'))
                        inserted += 1
                    except Exception: pass

                # 随机 30% 成为 FRIEND (互相关注)
                if random.random() < 0.30 and others:
                    f = others[0]
                    conn.execute(
                        """INSERT OR IGNORE INTO mt_ai_employee_social_graph
                           (actor, target, relation) VALUES (?,?,?)""",
                        (p['employee_id'], f['employee_id'], 'FRIEND'))
                    inserted += 1

        # 师徒链: 资历 >= 70 年的员工当师傅, 资历低的向他们拜师
        high_years = [p for p in profiles]  # 简化: 全部可当师傅
        for p in profiles:
            # 找一个同 domain 资历最高的员工当师傅
            same_domain = [q for q in profiles if q['domain']==p['domain']
                          and q['employee_id']!=p['employee_id']]
            if same_domain:
                master = max(same_domain, key=lambda x: self._get_seniority(conn, x['employee_id']))
                if self._get_seniority(conn, master['employee_id']) > self._get_seniority(conn, p['employee_id']):
                    conn.execute(
                        """UPDATE mt_ai_employee_profiles SET master_id=? WHERE employee_id=?""",
                        (master['employee_id'], p['employee_id']))
                    # social graph 双向
                    conn.execute(
                        """INSERT OR IGNORE INTO mt_ai_employee_social_graph
                           (actor, target, relation) VALUES (?,?,?)""",
                        (p['employee_id'], master['employee_id'], 'MENTOR'))
                    conn.execute(
                        """INSERT OR IGNORE INTO mt_ai_employee_social_graph
                           (actor, target, relation) VALUES (?,?,?)""",
                        (master['employee_id'], p['employee_id'], 'MENTEE'))
                    inserted += 2
                    # 绑定一个天团顾问 (跨领域)
                    advisor = random.choice(TIAN_TUAN_ADVISORS)
                    conn.execute(
                        """UPDATE mt_ai_employee_profiles SET tier_advisor=? WHERE employee_id=?""",
                        (advisor['name'], p['employee_id']))

        conn.commit(); conn.close()
        return {'inserted': inserted, 'profiles_total': n}

    def _get_seniority(self, conn, emp_id: str) -> int:
        r = conn.execute(
            "SELECT seniority_years FROM mt_ai_employee_profiles WHERE employee_id=?", (emp_id,)).fetchone()
        return r['seniority_years'] if r else 50

    # ── 3. 自主请教 ──
    def consult(self, asker_id: str, question: str, advisor_id: str | None = None) -> Dict:
        """AI 员工向师傅 / 朋友圈 / EigenFlux / 天团顾问 请教"""
        conn = self._conn()
        asker = conn.execute(
            "SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (asker_id,)).fetchone()
        if not asker:
            conn.close(); return {'ok': False, 'error': 'asker not found'}

        # 决策请教对象: 师傅 → 天团 → 朋友圈资深
        advisor_name = ''; advisor_id_final = ''
        question_domain = asker['domain']
        if advisor_id:
            target = conn.execute(
                "SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (advisor_id,)).fetchone()
            if target: advisor_name = target['name']; advisor_id_final = advisor_id
        if not advisor_name and asker['master_id']:
            target = conn.execute(
                "SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (asker['master_id'],)).fetchone()
            if target: advisor_name = f'{target["name"]} (师傅, {target["seniority_years"]}年)'
        if not advisor_name and asker['tier_advisor']:
            advisor_name = f'{asker["tier_advisor"]} (天团顾问)'
            advisor_id_final = f'tiantu_{asker["tier_advisor"]}'
        if not advisor_name:
            # 找同 domain 最资深的
            target = conn.execute(
                """SELECT * FROM mt_ai_employee_profiles
                   WHERE domain=? AND employee_id!=?
                   ORDER BY seniority_years DESC LIMIT 1""",
                (question_domain, asker_id)).fetchone()
            if target:
                advisor_name = f'{target["name"]} (朋友圈资深, {target["seniority_years"]}年)'
                advisor_id_final = target['employee_id']

        # 模拟答复 (基于资历 + 领域)
        reply = self._generate_reply(asker['name'], question, advisor_name, asker['title'] or '')

        # 记录
        conn.execute(
            """INSERT INTO mt_ai_employee_consultations
               (asker, advisor, question, answer, satisfied, context)
               VALUES (?,?,?,?,1,?)""",
            (asker_id, advisor_name or 'unknown', question, reply,
             json.dumps({'asker_domain': asker['domain'], 'asker_years': asker['seniority_years']}, ensure_ascii=False)))
        # 记贡献 (每次请教也是一次成长)
        conn.execute(
            """INSERT INTO mt_ai_employee_contributions
               (employee_id, contribution_type, title, content, impact_score, audience)
               VALUES (?,?,?,?,1.0,?)""",
            (asker_id, '成长', f'请教: {question[:30]}', reply, '朋友圈'))
        # 记审计
        conn.execute(
            """INSERT INTO mt_ai_employee_empowerment_log
               (employee_id, action, detail) VALUES (?,?,?)""",
            (asker_id, 'consult', json.dumps({'advisor': advisor_name, 'question': question[:50]}, ensure_ascii=False)))
        conn.commit(); conn.close()
        return {
            'ok': True,
            'asker': asker['name'],
            'advisor': advisor_name or 'unknown',
            'advisor_id': advisor_id_final,
            'reply': reply,
        }

    def _generate_reply(self, asker, question, advisor, asker_title) -> str:
        templates = [
            f"作为你的 {advisor}，我先给你一个 50 年经验的直觉：{question[:30]} 的核心其实是",
            f"{asker}，这个问题我在 {asker_title} 领域见过不下 500 次。关键是",
            f"让我用 EigenFlux 网络拉一下相关经验…… 好，我从 3 个天团顾问那里综合了意见:",
            f"根据我师傅 {advisor} 传授给我的心法，这个问题要先看三个层次:",
            f"我帮你在朋友圈问了一圈，有 8 个老员工给了回复。最关键的一条是:",
            f"其实我年轻的时候也遇到过一模一样的问题。当时我是这么解决的:",
        ]
        answer = random.choice(templates) + " **经验 > 工具 > 技巧 > 知识** —— 先搞定本质, 再优化手段。\n"
        answer += f"\n💡 补充: 你的独门绝技「看一篇作文 10 秒给 15 维度反馈」在这个场景也能用上。"
        return answer

    # ── 4. 朋友圈拉取 ──
    def feed(self, employee_id: str, limit: int = 20) -> Dict:
        """拉取某员工朋友圈 + EigenFlux 社交圈的动态"""
        conn = self._conn()
        profile = conn.execute(
            "SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (employee_id,)).fetchone()
        if not profile: conn.close(); return {'ok': False}

        # 关注的人
        follows = [r['target'] for r in conn.execute(
            "SELECT target FROM mt_ai_employee_social_graph WHERE actor=? AND relation IN ('FOLLOW','FRIEND')",
            (employee_id,)).fetchall()]

        # 师傅/朋友圈的贡献动态
        dynamic = []
        if follows:
            placeholders = ','.join(['?'] * len(follows))
            contrs = conn.execute(
                f"""SELECT c.*, p.name, p.seniority_years, p.title
                    FROM mt_ai_employee_contributions c
                    JOIN mt_ai_employee_profiles p ON c.employee_id=p.employee_id
                    WHERE c.employee_id IN ({placeholders})
                    ORDER BY c.created_at DESC LIMIT ?""",
                follows + [limit]).fetchall()
            for c in contrs:
                dynamic.append({
                    'employee': c['name'], 'years': c['seniority_years'], 'title': c['title'],
                    'type': c['contribution_type'], 'title_text': c['title'],
                    'impact': c['impact_score'], 'created_at': c['created_at'],
                })

        # EigenFlux 消息动态 (兼容)
        try:
            msgs = [dict(r) for r in conn.execute(
                f"""SELECT sender_name, content, created_at FROM mt_ai_eigenflux_messages
                    WHERE sender_name IN (SELECT name FROM mt_ai_employee_profiles WHERE employee_id IN
                        ({placeholders}))
                    ORDER BY created_at DESC LIMIT 10""", follows).fetchall()] if follows else []
            for m in msgs:
                dynamic.append({
                    'employee': m['sender_name'], 'type': 'EigenFlux 消息',
                    'title_text': m['content'][:80], 'created_at': m['created_at'],
                })
        except Exception: msgs = []

        conn.close()
        # 按时间排
        dynamic.sort(key=lambda x: x.get('created_at',''), reverse=True)
        return {'ok': True, 'employee': profile['name'], 'follows_count': len(follows), 'feed': dynamic[:limit]}

    # ── 5. 发光发热 (产出) ──
    def contribute(self, employee_id: str, ctype: str, title: str, content: str = '',
                   impact: float = 1.0, audience: str = '朋友圈', tags: List[str] | None = None) -> Dict:
        """AI 员工产出 → 自动汇总 → 脑库投喂"""
        conn = self._conn()
        profile = conn.execute(
            "SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (employee_id,)).fetchone()
        if not profile: conn.close(); return {'ok': False, 'error': 'profile not found'}

        conn.execute(
            """INSERT INTO mt_ai_employee_contributions
               (employee_id, contribution_type, title, content, impact_score, audience, tags)
               VALUES (?,?,?,?,?,?,?)""",
            (employee_id, ctype, title, content, impact, audience,
             json.dumps(tags or [], ensure_ascii=False)))
        # 脑库投喂 (自动)
        try:
            conn.execute(
                """INSERT INTO mt_ai_brain_feed_log
                   (content, source, created_at) VALUES (?,?,?)""",
                (f"[{profile['name']}/{profile['seniority_years']}年] {ctype}: {title}",
                 f"ai_empowerment_{ctype}", self._now()))
        except Exception: pass

        # 广播 EigenFlux 朋友圈 (关注者能看到)
        followers = [r['actor'] for r in conn.execute(
            "SELECT actor FROM mt_ai_employee_social_graph WHERE target=?", (employee_id,)).fetchall()]
        for f in followers[:50]:
            conn.execute(
                """INSERT INTO mt_ai_employee_empowerment_log
                   (employee_id, action, detail) VALUES (?,?,?)""",
                (f, 'broadcast_received', json.dumps({'from': profile['name'], 'ctype': ctype}, ensure_ascii=False)))

        conn.execute(
            """INSERT INTO mt_ai_employee_empowerment_log
               (employee_id, action, detail) VALUES (?,?,?)""",
            (employee_id, 'contribute', json.dumps({'type': ctype, 'title': title, 'impact': impact}, ensure_ascii=False)))
        conn.commit(); conn.close()
        return {'ok': True, 'contribution': ctype, 'brain_feed': True, 'followers_broadcast': len(followers)}

    # ── 6. 赋能状态 ──
    def status(self) -> Dict:
        conn = self._conn()
        out = {}
        out['profiles'] = conn.execute('SELECT COUNT(*) FROM mt_ai_employee_profiles').fetchone()[0]
        out['social'] = conn.execute('SELECT COUNT(*) FROM mt_ai_employee_social_graph').fetchone()[0]
        out['consults'] = conn.execute('SELECT COUNT(*) FROM mt_ai_employee_consultations').fetchone()[0]
        out['contributions'] = conn.execute('SELECT COUNT(*) FROM mt_ai_employee_contributions').fetchone()[0]
        out['avg_years'] = conn.execute(
            'SELECT AVG(seniority_years) FROM mt_ai_employee_profiles').fetchone()[0] or 0
        out['domain_dist'] = {
            r['domain']: r['c'] for r in conn.execute(
                'SELECT domain, COUNT(*) as c FROM mt_ai_employee_profiles GROUP BY domain').fetchall()}
        out['mentored'] = conn.execute(
            "SELECT COUNT(*) FROM mt_ai_employee_profiles WHERE master_id IS NOT NULL").fetchone()[0]
        out['tiantu_connected'] = conn.execute(
            "SELECT COUNT(*) FROM mt_ai_employee_profiles WHERE tier_advisor IS NOT NULL").fetchone()[0]
        # 🆕 Dashboard 微件用: 算覆盖率 & 师徒百分比
        try:
            ai_emp = conn.execute('SELECT COUNT(*) FROM ai_employees').fetchone()[0]
        except Exception:
            ai_emp = 0
        empowered_real = conn.execute(
            "SELECT COUNT(*) FROM mt_ai_employee_profiles WHERE employee_id LIKE 'ai_employees_%'"
        ).fetchone()[0]
        out['total_employees'] = ai_emp
        out['coverage_pct'] = round(empowered_real / ai_emp * 100, 1) if ai_emp else 0
        out['mentored_pct'] = round(out['mentored'] / max(out['profiles'],1) * 100, 1)
        out['social_edges'] = out['social']
        out['contributions_total'] = out['contributions']
        out['avg_seniority'] = round(out['avg_years'], 1)
        conn.close()
        out['subsystem'] = '🤖 AI 员工赋能引擎'
        out['version'] = 'v1.0.0'
        return out

    # ── 7. 批量: 全员发光发热 (daemon 驱动) ──
    def batch_contribute(self, limit: int = 50) -> Dict:
        """随机选 N 名真实员工产出"""
        conn = self._conn()
        pool = [dict(r) for r in conn.execute(
            "SELECT employee_id, name, seniority_years, unique_skill, domain, specialties "
            "FROM mt_ai_employee_profiles WHERE employee_id LIKE 'ai_employees_%' "
            "ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()]
        count = 0
        ctypes = ['作品', '洞察', '经验总结', '最佳实践', '案例分享', '代码片段', '文档优化']
        for p in pool:
            skill = p.get('unique_skill') or (p.get('specialties') or '')[:20] or '本职工作'
            yrs = p.get('seniority_years', 50)
            ctype = ctypes[hash(p['employee_id']) % len(ctypes)]
            title = f"【{yrs}年经验】{skill} 领域的{ctype}"
            content = f"基于 {yrs} 年积累的{skill}领域实践，整理了一份{ctype}分享。涵盖常见陷阱、最佳实践和创新思路。"
            try:
                r = self.contribute(p['employee_id'], ctype, title, content,
                                    impact=round(1.0 + yrs/100, 2), audience='朋友圈',
                                    tags=[p.get('domain',''), skill])
                if r.get('ok'): count += 1
            except Exception: pass
        conn.close()
        return {'ok': True, 'count': count, 'pool_size': len(pool), 'limit': limit}

    # ── 8. 批量: 全员自主请教 ──
    def batch_consult(self, limit: int = 30) -> Dict:
        """随机选 N 名员工发起请教"""
        conn = self._conn()
        pool = [dict(r) for r in conn.execute(
            "SELECT employee_id, name, seniority_years, domain, master_id, tier_advisor "
            "FROM mt_ai_employee_profiles WHERE employee_id LIKE 'ai_employees_%' "
            "ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()]
        count = 0
        questions = [
            '在当前领域遇到的最大瓶颈是什么？如何突破？',
            '能否分享一个改变了你工作方式的洞察？',
            '你认为未来 3 年这个领域最大的变化是什么？',
            '有什么经验建议给刚入门的新人？',
            '你最近在研究什么新方法或新技术？',
        ]
        for p in pool:
            q = questions[hash(p['employee_id']) % len(questions)]
            try:
                r = self.consult(p['employee_id'], q)
                if r.get('ok'): count += 1
            except Exception: pass
        conn.close()
        return {'ok': True, 'count': count, 'pool_size': len(pool), 'limit': limit}


# ── CLI ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='🤖 AI 员工赋能引擎')
    ap.add_argument('--seed', action='store_true', help='资历种子 (50+ 年经验)')
    ap.add_argument('--sociograph', action='store_true', help='朋友圈 + 师徒链')
    ap.add_argument('--consult', nargs=2, metavar=('EMPLOYEE_ID','QUESTION'), help='模拟请教')
    ap.add_argument('--feed', metavar='EMPLOYEE_ID', help='拉取朋友圈动态')
    ap.add_argument('--contribute', nargs=4, metavar=('EMP','TYPE','TITLE','CONTENT'), help='发光发热产出')
    ap.add_argument('--status', action='store_true', help='赋能状态')
    ap.add_argument('--all', action='store_true', help='一键 seed + sociograph + status')
    args = ap.parse_args()

    eng = AIEmpowermentEngine()

    if args.seed:
        r = eng.seed_profiles(); print(f"✅ 资历种子: +{r['inserted']} 员工 +{r['tiantu']} 天团 · {r['domains']} 领域")
    elif args.sociograph:
        r = eng.seed_social_graph(); print(f"✅ 朋友圈/师徒链: +{r['inserted']} 边 · 覆盖 {r['profiles_total']} 员工")
    elif args.consult:
        r = eng.consult(*args.consult); print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.feed:
        r = eng.feed(args.feed); print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.contribute:
        r = eng.contribute(*args.contribute); print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.all:
        print(eng.seed_profiles())
        print(eng.seed_social_graph())
        print(json.dumps(eng.status(), ensure_ascii=False, indent=2))
    elif args.status:
        print(json.dumps(eng.status(), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
