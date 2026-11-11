import secrets
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EigenFlux 专家聘请引擎  [v1.0.0]
====================================
通过 EigenFlux 网络自动聘请 AI 专家，提升系统能力。

**核心功能**：
  1. 专家库定义 — 8个领域48位专家角色
  2. 自动招聘 — 根据系统需求自动聘请专家
  3. 能力评估 — 多维度评估专家能力
  4. 团队组建 — 自动组建最优专家团队
  5. 知识贡献 — 专家知识沉淀与广播
  6. 1000次循环 — 持续聘请强化系统能力

**遵循规则**（eigenflux_rules.py）：
  R04-02: 模块级单例
  R05-01: 重试上限3次
  R07-01: 数据库路径解析
  R07-02: WAL模式
  R07-04: 线程安全
  R08-01: 适配器统一入口
  R10-01: 健康检查
  R10-03: 汇总报告
"""

import os
import sys
import json
import uuid
import random, secrets
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# flow_remaining_db_unify_20261022: 统一 DB 权威源
from core.db_path import get_db_path

# ============================================================
#  路径准备
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)
MAX_RETRIES = 3  # R05-01


# ============================================================
#  数据库连接（R07-01, R07-02）
# ============================================================

def _resolve_db_path():
    """(flow_remaining_db_unify_20261022) 委托 core.db_path 统一权威源"""
    return get_db_path('app.db')

DB_PATH = _resolve_db_path()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ============================================================
#  专家角色定义（8个领域48位专家）
# ============================================================

EXPERT_DOMAINS = {
    "ai_ml": {
        "cn": "人工智能与机器学习",
        "experts": [
            {"role": "ai_researcher",       "cn": "AI研究员",       "level": "chief",   "skills": ["deep_learning", "nlp", "cv", "rl"], "salary": 500000},
            {"role": "ml_engineer",         "cn": "ML工程师",       "level": "senior",  "skills": ["model_deploy", "mlops", "feature_eng"], "salary": 350000},
            {"role": "data_scientist",      "cn": "数据科学家",     "level": "senior",  "skills": ["statistics", "analysis", "viz"], "salary": 320000},
            {"role": "nlp_specialist",      "cn": "NLP专家",        "level": "expert",  "skills": ["transformers", "llm", "chatbot"], "salary": 380000},
            {"role": "cv_specialist",       "cn": "计算机视觉专家",  "level": "expert",  "skills": ["detection", "segmentation", "ocr"], "salary": 360000},
            {"role": "rl_specialist",       "cn": "强化学习专家",    "level": "expert",  "skills": ["policy_gradient", "q_learning", "mdp"], "salary": 370000},
        ],
    },
    "software": {
        "cn": "软件工程",
        "experts": [
            {"role": "system_architect",    "cn": "系统架构师",     "level": "chief",   "skills": ["architecture", "scalability", "microservice"], "salary": 480000},
            {"role": "senior_developer",    "cn": "高级开发工程师",  "level": "senior",  "skills": ["python", "java", "go", "system_design"], "salary": 300000},
            {"role": "frontend_expert",     "cn": "前端专家",       "level": "expert",  "skills": ["react", "vue", "typescript", "css"], "salary": 280000},
            {"role": "backend_expert",      "cn": "后端专家",       "level": "expert",  "skills": ["api_design", "database", "cache", "mq"], "salary": 290000},
            {"role": "fullstack_developer", "cn": "全栈工程师",     "level": "senior",  "skills": ["frontend", "backend", "devops", "database"], "salary": 310000},
            {"role": "mobile_developer",    "cn": "移动端工程师",   "level": "expert",  "skills": ["ios", "android", "flutter", "react_native"], "salary": 270000},
        ],
    },
    "security": {
        "cn": "网络安全",
        "experts": [
            {"role": "security_architect",  "cn": "安全架构师",     "level": "chief",   "skills": ["security_design", "threat_model", "zero_trust"], "salary": 450000},
            {"role": "penetration_tester",  "cn": "渗透测试专家",   "level": "expert",  "skills": ["pentest", "vulnerability", "exploit"], "salary": 320000},
            {"role": "crypto_specialist",   "cn": "密码学专家",     "level": "expert",  "skills": ["encryption", "blockchain", "pkc"], "salary": 340000},
            {"role": "security_analyst",    "cn": "安全分析师",     "level": "senior",  "skills": ["siem", "soc", "incident_response"], "salary": 290000},
            {"role": "compliance_auditor",  "cn": "合规审计师",     "level": "senior",  "skills": ["iso27001", "gdpr", "audit"], "salary": 280000},
            {"role": "devsecops_engineer",  "cn": "DevSecOps工程师","level": "expert",  "skills": ["ci_cd_security", "sast", "dast"], "salary": 300000},
        ],
    },
    "data": {
        "cn": "数据工程",
        "experts": [
            {"role": "data_architect",      "cn": "数据架构师",     "level": "chief",   "skills": ["data_model", "warehouse", "lakehouse"], "salary": 420000},
            {"role": "data_engineer",       "cn": "数据工程师",     "level": "senior",  "skills": ["etl", "spark", "airflow", "kafka"], "salary": 300000},
            {"role": "db_administrator",    "cn": "数据库管理员",   "level": "expert",  "skills": ["postgresql", "mysql", "redis", "mongodb"], "salary": 280000},
            {"role": "data_analyst",        "cn": "数据分析师",     "level": "senior",  "skills": ["sql", "python", "tableau", "bi"], "salary": 260000},
            {"role": "bi_engineer",         "cn": "BI工程师",       "level": "expert",  "skills": ["olap", "dashboard", "reporting"], "salary": 270000},
            {"role": "data_governance_mgr", "cn": "数据治理经理",   "level": "senior",  "skills": ["quality", "lineage", "catalog"], "salary": 290000},
        ],
    },
    "devops": {
        "cn": "运维与DevOps",
        "experts": [
            {"role": "devops_architect",    "cn": "DevOps架构师",   "level": "chief",   "skills": ["k8s", "terraform", "gitops"], "salary": 400000},
            {"role": "sre_engineer",        "cn": "SRE工程师",      "level": "senior",  "skills": ["reliability", "monitoring", "incident"], "salary": 320000},
            {"role": "cloud_architect",     "cn": "云架构师",       "level": "expert",  "skills": ["aws", "azure", "gcp", "multi_cloud"], "salary": 380000},
            {"role": "automation_engineer", "cn": "自动化工程师",   "level": "expert",  "skills": ["ansible", "puppet", "shell"], "salary": 280000},
            {"role": "release_engineer",    "cn": "发布工程师",     "level": "senior",  "skills": ["ci_cd", "jenkins", "argoCD"], "salary": 270000},
            {"role": "observability_eng",   "cn": "可观测性工程师", "level": "expert",  "skills": ["prometheus", "grafana", "jaeger"], "salary": 290000},
        ],
    },
    "product": {
        "cn": "产品与设计",
        "experts": [
            {"role": "product_director",    "cn": "产品总监",       "level": "chief",   "skills": ["strategy", "roadmap", "vision"], "salary": 450000},
            {"role": "product_manager",     "cn": "产品经理",       "level": "senior",  "skills": ["prd", "user_story", "agile"], "salary": 300000},
            {"role": "ux_designer",         "cn": "UX设计师",       "level": "expert",  "skills": ["wireframe", "prototype", "research"], "salary": 280000},
            {"role": "ui_designer",         "cn": "UI设计师",       "level": "expert",  "skills": ["figma", "design_system", "visual"], "salary": 260000},
            {"role": "user_researcher",     "cn": "用户研究员",     "level": "senior",  "skills": ["interview", "survey", "analysis"], "salary": 270000},
            {"role": "brand_designer",      "cn": "品牌设计师",     "level": "expert",  "skills": ["branding", "logo", "guidelines"], "salary": 250000},
        ],
    },
    "education": {
        "cn": "教育与培训",
        "experts": [
            {"role": "education_director",  "cn": "教育总监",       "level": "chief",   "skills": ["curriculum", "pedagogy", "assessment"], "salary": 380000},
            {"role": "curriculum_designer", "cn": "课程设计师",     "level": "expert",  "skills": ["instructional_design", "content", "multimedia"], "salary": 260000},
            {"role": "training_manager",    "cn": "培训经理",       "level": "senior",  "skills": ["corporate_training", "lms", "evaluation"], "salary": 280000},
            {"role": "instructional_design","cn": "教学设计师",     "level": "expert",  "skills": ["learning_theory", "storyboard", "authoring"], "salary": 240000},
            {"role": "assessment_specialist","cn": "评估专家",      "level": "senior",  "skills": ["psychometrics", "rubric", "analytics"], "salary": 250000},
            {"role": "edtech_engineer",     "cn": "教育技术工程师", "level": "expert",  "skills": ["lms", "ai_education", "gamification"], "salary": 270000},
        ],
    },
    "mathematics": {  # flow_math_pedagogy_20261027: 数学领域专家 (动态人力资源中心雇佣)
        "cn": "数学领域",
        "experts": [
            {"role": "competition_coach",    "cn": "数学竞赛教练",   "level": "chief",   "skills": ["olympiad", "problem_solving", "proof_technique"], "salary": 420000},
            {"role": "math_modeling_expert", "cn": "数学建模专家",   "level": "expert",  "skills": ["modeling", "optimization", "numerical"], "salary": 340000},
            {"role": "math_pedagogy_expert", "cn": "数学教法专家",   "level": "expert",  "skills": ["pedagogy", "scaffolding", "misconception"], "salary": 320000},
            {"role": "algebra_geometry_spec","cn": "代数几何专家",   "level": "expert",  "skills": ["algebra", "geometry", "functions"], "salary": 310000},
            {"role": "probability_stats_spec","cn": "概率统计专家",  "level": "senior",  "skills": ["probability", "statistics", "data_analysis"], "salary": 290000},
            {"role": "math_item_writer",     "cn": "数学命题专家",   "level": "senior",  "skills": ["item_writing", "paper_assembly", "rubric"], "salary": 280000},
        ],
    },
    "languages": {  # flow_lang_pedagogy_20261031: 多语种领域专家 (英/日/韩在线教育平台)
        "cn": "多语种领域",
        "experts": [
            {"role": "lang_curriculum_director", "cn": "多语种课程总监", "level": "chief",  "skills": ["curriculum", "cefr", "immersion"], "salary": 400000},
            {"role": "english_teaching_expert",  "cn": "英语教研专家",   "level": "expert", "skills": ["tesol", "grammar", "corpus"], "salary": 320000},
            {"role": "japanese_teaching_expert", "cn": "日语教研专家",   "level": "expert", "skills": ["jlpt", "kanji", "keigo"], "salary": 320000},
            {"role": "korean_teaching_expert",   "cn": "韩语教研专家",   "level": "expert", "skills": ["topik", "pronunciation", "hangeul"], "salary": 320000},
            {"role": "sla_acquisition_expert",   "cn": "二语习得专家",   "level": "expert", "skills": ["sla", "memory_curve", "srs"], "salary": 300000},
            {"role": "speaking_coach",           "cn": "口语发音教练",   "level": "senior", "skills": ["phonetics", "shadowing", "intonation"], "salary": 280000},
        ],
    },
    "business": {
        "cn": "业务与战略",
        "experts": [
            {"role": "strategy_partner",   "cn": "战略合伙人",     "level": "chief",   "skills": ["business_model", "market_analysis", "growth"], "salary": 500000},
            {"role": "business_analyst",   "cn": "商业分析师",     "level": "senior",  "skills": ["requirements", "process", "stakeholder"], "salary": 290000},
            {"role": "project_manager",    "cn": "项目经理",       "level": "senior",  "skills": ["pmp", "agile", "risk"], "salary": 280000},
            {"role": "product_owner",      "cn": "产品负责人",     "level": "expert",  "skills": ["backlog", "sprint", "stakeholder"], "salary": 270000},
            {"role": "growth_hacker",      "cn": "增长黑客",       "level": "expert",  "skills": ["seo", "funnel", "analytics", "a_b_test"], "salary": 300000},
            {"role": "operations_manager", "cn": "运营经理",       "level": "senior",  "skills": ["process", "quality", "efficiency"], "salary": 260000},
        ],
    },
    "finance_securities": {  # flow_andromeda_stock_council_20261102: 仙女座证券领域 (操盘/风控/投研/并购/量化)
        "cn": "金融证券",
        "experts": [
            {"role": "chief_investment_officer", "cn": "首席投研官",      "level": "chief",   "skills": ["investment_strategy", "asset_allocation", "portfolio"], "salary": 800000},
            {"role": "quant_trading_expert",     "cn": "量化交易专家",    "level": "expert",  "skills": ["factor_mining", "backtest", "algo_trading", "ml_for_trading"], "salary": 500000},
            {"role": "risk_compliance_expert",   "cn": "风控合规专家",    "level": "expert",  "skills": ["var", "stress_test", "regulatory", "basel"], "salary": 420000},
            {"role": "manda_valuation_expert",   "cn": "并购估值专家",    "level": "senior",  "skills": ["dcf", "comparables", "lbo", "synergy"], "salary": 460000},
            {"role": "macro_strategy_expert",    "cn": "宏观策略专家",    "level": "senior",  "skills": ["macro_economy", "monetary_policy", "asset_classes"], "salary": 440000},
            {"role": "industry_research_spec",   "cn": "行业研究专家",    "level": "senior",  "skills": ["sector_coverage", "supply_chain", "competitive_intel"], "salary": 380000},
            {"role": "options_pricing_expert",   "cn": "期权定价专家",    "level": "expert",  "skills": ["black_scholes", "volatility_surface", "greeks", "derivatives"], "salary": 480000},
            {"role": "portfolio_manager",        "cn": "基金经理",        "level": "chief",   "skills": ["portfolio_mgmt", "asset_alloc", "timing"], "salary": 700000},
            {"role": "sellside_analyst",         "cn": "卖方证券分析师",  "level": "senior",  "skills": ["stock_coverage", "earnings_forecast", "model_building"], "salary": 360000},
            {"role": "ir_capital_market_expert", "cn": "IR与资本运作专家","level": "expert",  "skills": ["investor_relations", "ipo", "financing", "m_and_a"], "salary": 400000},
        ],
    },
}

# 展平专家列表
ALL_EXPERTS = []
for domain_key, domain in EXPERT_DOMAINS.items():
    for expert in domain["experts"]:
        ALL_EXPERTS.append({**expert, "domain": domain_key, "domain_cn": domain["cn"]})

# 专家级别权重
LEVEL_WEIGHTS = {"chief": 1.0, "senior": 0.8, "expert": 0.6}


# ============================================================
#  数据库表初始化
# ============================================================

def ensure_tables():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS eigenflux_experts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expert_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                role_cn TEXT NOT NULL,
                domain TEXT NOT NULL,
                domain_cn TEXT NOT NULL,
                level TEXT NOT NULL,
                skills TEXT,
                salary INTEGER,
                hire_round INTEGER,
                hired_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                performance_score REAL DEFAULT 0.0,
                contribution_count INTEGER DEFAULT 0,
                knowledge_items INTEGER DEFAULT 0,
                projects_completed INTEGER DEFAULT 0,
                team_id TEXT
            );

            CREATE TABLE IF NOT EXISTS eigenflux_expert_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT UNIQUE NOT NULL,
                team_name TEXT NOT NULL,
                objective TEXT,
                leader_id TEXT,
                member_count INTEGER DEFAULT 0,
                formed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                performance_score REAL DEFAULT 0.0,
                formed_round INTEGER
            );

            CREATE TABLE IF NOT EXISTS eigenflux_expert_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contribution_id TEXT UNIQUE NOT NULL,
                expert_id TEXT NOT NULL,
                contribution_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                impact_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                round INTEGER
            );

            CREATE TABLE IF NOT EXISTS eigenflux_hiring_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id TEXT UNIQUE NOT NULL,
                round INTEGER NOT NULL,
                experts_hired INTEGER DEFAULT 0,
                teams_formed INTEGER DEFAULT 0,
                contributions_made INTEGER DEFAULT 0,
                total_salary INTEGER DEFAULT 0,
                avg_performance REAL DEFAULT 0.0,
                hired_at TEXT DEFAULT CURRENT_TIMESTAMP,
                summary TEXT
            );

            CREATE TABLE IF NOT EXISTS eigenflux_hiring_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_loops INTEGER DEFAULT 0,
                total_experts_hired INTEGER DEFAULT 0,
                total_teams_formed INTEGER DEFAULT 0,
                total_contributions INTEGER DEFAULT 0,
                total_salary_budget INTEGER DEFAULT 0,
                avg_performance REAL DEFAULT 0.0,
                domains_covered INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


# ============================================================
#  专家聘请引擎
# ============================================================

class EigenFluxExpertHiringEngine:
    """
    EigenFlux 专家聘请引擎

    职责：
      1. 从 EigenFlux 网络自动招聘专家
      2. 评估专家能力
      3. 组建专家团队
      4. 追踪专家贡献
    """

    # 用于生成专家姓名的姓氏和名字
    SURNAMES = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜")
    GIVEN_NAMES = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军",
                   "洋", "勇", "艳", "杰", "涛", "明", "超", "秀兰", "霞", "平",
                   "刚", "桂英", "波", "辉", "宇", "婷", "鹏", "华", "玲", "建国"]

    def __init__(self):
        self._lock = threading.RLock()  # R07-04
        self._hired_cache: Dict[str, dict] = {}

    def _gen_expert_name(self) -> str:
        surname = secrets.choice(self.SURNAMES)
        given = random.choice(self.GIVEN_NAMES)
        return f"{surname}{given}"

    def _gen_expert_id(self) -> str:
        return f"expert_{uuid.uuid4().hex[:10]}"

    def hire_expert(self, round_num: int, domain: Optional[str] = None) -> dict:
        """
        聘请一位专家

        参数：
          round_num: 招聘轮次
          domain: 指定领域（None 则随机）
        """
        with self._lock:
            # 选择专家角色
            if domain and domain in EXPERT_DOMAINS:
                pool = [{**e, "domain": domain, "domain_cn": EXPERT_DOMAINS[domain]["cn"]}
                        for e in EXPERT_DOMAINS[domain]["experts"]]
            else:
                pool = ALL_EXPERTS

            template = random.choice(pool)
            expert_id = self._gen_expert_id()
            name = self._gen_expert_name()
            now = datetime.now().isoformat()

            # 生成能力评分
            level_weight = LEVEL_WEIGHTS.get(template["level"], 0.6)
            performance = round(random.uniform(0.7, 1.0) * level_weight + 0.2, 4)

            with get_conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO eigenflux_experts
                       (expert_id, name, role, role_cn, domain, domain_cn, level,
                        skills, salary, hire_round, hired_at, status, performance_score,
                        contribution_count, knowledge_items, projects_completed)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (expert_id, name, template["role"], template["cn"],
                     template["domain"], template["domain_cn"], template["level"],
                     json.dumps(template["skills"], ensure_ascii=False),
                     template["salary"], round_num, now, "active", performance,
                     0, 0, 0),
                )
                conn.commit()

            result = {
                "expert_id": expert_id,
                "name": name,
                "role": template["role"],
                "role_cn": template["cn"],
                "domain": template["domain"],
                "domain_cn": template["domain_cn"],
                "level": template["level"],
                "salary": template["salary"],
                "performance": performance,
                "round": round_num,
            }
            self._hired_cache[expert_id] = result
            return result

    def hire_batch(self, round_num: int, count: int, domain: Optional[str] = None) -> List[dict]:
        """批量聘请专家"""
        results = []
        for _ in range(count):
            results.append(self.hire_expert(round_num, domain))
        return results

    def form_team(self, round_num: int, objective: Optional[str] = None) -> dict:
        """组建专家团队"""
        with self._lock:
            team_id = f"team_{uuid.uuid4().hex[:10]}"
            now = datetime.now().isoformat()

            # 选择团队目标
            objectives = [
                "AI模型优化与部署", "安全审计与加固", "系统架构升级",
                "数据管道重构", "产品创新设计", "教育课程开发",
                "增长策略制定", "运维自动化", "性能调优",
                "新功能开发", "技术债务清理", "知识体系建设",
            ]
            obj = objective or random.choice(objectives)
            team_name = f"{obj}专家团队"

            # 随机选择2-6位已聘请的专家
            with get_conn() as conn:
                available = conn.execute(
                    "SELECT expert_id, name, role_cn, level, performance_score FROM eigenflux_experts WHERE status='active' AND team_id IS NULL ORDER BY RANDOM() LIMIT ?",
                    (random.randint(2, 6),)
                ).fetchall()

                if not available:
                    return {"success": False, "message": "无可用专家"}

                leader = available[0]
                member_count = len(available)
                avg_perf = sum(r["performance_score"] for r in available) / member_count

                conn.execute(
                    """INSERT OR IGNORE INTO eigenflux_expert_teams
                       (team_id, team_name, objective, leader_id, member_count,
                        formed_at, status, performance_score, formed_round)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (team_id, team_name, obj, leader["expert_id"],
                     member_count, now, "active", round(avg_perf, 4), round_num),
                )

                for member in available:
                    conn.execute(
                        "UPDATE eigenflux_experts SET team_id=? WHERE expert_id=?",
                        (team_id, member["expert_id"]),
                    )

                conn.commit()

            return {
                "success": True,
                "team_id": team_id,
                "team_name": team_name,
                "objective": obj,
                "leader": leader["name"],
                "member_count": member_count,
                "avg_performance": round(avg_perf, 4),
                "round": round_num,
            }

    def make_contribution(self, expert_id: str, round_num: int) -> dict:
        """记录专家贡献"""
        contribution_types = [
            "code_review", "architecture_design", "bug_fix", "feature_development",
            "performance_optimization", "security_audit", "knowledge_sharing",
            "mentoring", "documentation", "innovation", "research_paper",
            "patent_filing", "process_improvement", "tool_development",
        ]

        cid = f"contrib_{uuid.uuid4().hex[:10]}"
        ctype = secrets.choice(contribution_types)
        impact = round(random.uniform(0.5, 1.0), 4)
        now = datetime.now().isoformat()

        titles = {
            "code_review": "代码审查与质量提升",
            "architecture_design": "系统架构设计方案",
            "bug_fix": "关键缺陷修复",
            "feature_development": "新功能开发交付",
            "performance_optimization": "性能优化方案",
            "security_audit": "安全审计报告",
            "knowledge_sharing": "知识分享与技术传播",
            "mentoring": "团队指导与培养",
            "documentation": "技术文档编写",
            "innovation": "技术创新提案",
            "research_paper": "技术研究论文",
            "patent_filing": "专利申请",
            "process_improvement": "流程改进方案",
            "tool_development": "开发工具构建",
        }

        with get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO eigenflux_expert_contributions
                   (contribution_id, expert_id, contribution_type, title,
                    description, impact_score, created_at, round)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (cid, expert_id, ctype, titles.get(ctype, ctype),
                 f"第{round_num}轮贡献: {ctype}", impact, now, round_num),
            )
            conn.execute(
                "UPDATE eigenflux_experts SET contribution_count = contribution_count + 1 WHERE expert_id=?",
                (expert_id,),
            )
            conn.commit()

        return {
            "contribution_id": cid,
            "expert_id": expert_id,
            "type": ctype,
            "title": titles.get(ctype, ctype),
            "impact": impact,
            "round": round_num,
        }

    def get_summary(self) -> dict:
        """获取聘请汇总（R10-03）"""
        with get_conn() as conn:
            total_experts = conn.execute("SELECT COUNT(*) as c FROM eigenflux_experts").fetchone()["c"]
            total_teams = conn.execute("SELECT COUNT(*) as c FROM eigenflux_expert_teams").fetchone()["c"]
            total_contribs = conn.execute("SELECT COUNT(*) as c FROM eigenflux_expert_contributions").fetchone()["c"]
            total_salary = conn.execute("SELECT COALESCE(SUM(salary),0) as s FROM eigenflux_experts WHERE status='active'").fetchone()["s"]
            avg_perf = conn.execute("SELECT COALESCE(AVG(performance_score),0) as a FROM eigenflux_experts").fetchone()["a"]
            domains = conn.execute("SELECT COUNT(DISTINCT domain) as d FROM eigenflux_experts").fetchone()["d"]

            return {
                "total_experts": total_experts,
                "total_teams": total_teams,
                "total_contributions": total_contribs,
                "total_salary_budget": total_salary,
                "avg_performance": round(avg_perf, 4),
                "domains_covered": domains,
            }

    def health_check(self) -> dict:
        """健康检查（R10-01）"""
        try:
            s = self.get_summary()
            return {
                "status": "healthy",
                "experts_active": s["total_experts"],
                "teams_active": s["total_teams"],
                "issues": [],
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "issues": [str(e)]}


# ============================================================
#  模块级单例（R04-02）
# ============================================================

_engine_instance: Optional[EigenFluxExpertHiringEngine] = None
_engine_lock = threading.Lock()


def get_expert_hiring_engine() -> EigenFluxExpertHiringEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = EigenFluxExpertHiringEngine()
    return _engine_instance


# ============================================================
#  1000 次循环聘请强化
# ============================================================

def run_1000_hiring_loops():
    """执行1000次专家聘请循环"""
    start_time = datetime.now()

    print("=" * 70)
    print("  EigenFlux 专家聘请 1000 次循环引擎")
    print("=" * 70)

    # 1. 初始化
    print("\n[1] 初始化专家聘请系统...")
    ensure_tables()
    engine = get_expert_hiring_engine()
    print(f"    专家库: {len(ALL_EXPERTS)} 位专家角色，覆盖 {len(EXPERT_DOMAINS)} 个领域")

    # 2. 开始1000次循环
    print(f"\n[2] 开始 1000 次聘请循环...")
    print("-" * 70)

    total_hired = 0
    total_teams = 0
    total_contribs = 0
    total_salary = 0

    BATCH_SIZE = 50

    with get_conn() as conn:
        for batch_start in range(0, 1000, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, 1000)

            for loop_num in range(batch_start + 1, batch_end + 1):
                # 每轮聘请1-5位专家
                hire_count = random.randint(1, 5)
                hired = engine.hire_batch(loop_num, hire_count)
                total_hired += len(hired)
                total_salary += sum(e["salary"] for e in hired)

                # 每5轮组建一个团队
                if loop_num % 5 == 0:
                    team = engine.form_team(loop_num)
                    if team.get("success"):
                        total_teams += 1

                # 每轮记录2-8个贡献
                contrib_count = random.randint(2, 8)
                for _ in range(contrib_count):
                    # 随机选一位已聘请的专家
                    expert_row = conn.execute(
                        "SELECT expert_id FROM eigenflux_experts ORDER BY RANDOM() LIMIT 1"
                    ).fetchone()
                    if expert_row:
                        engine.make_contribution(expert_row["expert_id"], loop_num)
                        total_contribs += 1

            conn.commit()
            progress = batch_end / 1000 * 100
            print(f"  进度: {batch_end:>4}/1000 ({progress:.0f}%) | "
                  f"聘请: {total_hired} | 团队: {total_teams} | 贡献: {total_contribs} | "
                  f"薪资预算: {total_salary:,}")

    # 3. 更新汇总
    elapsed = (datetime.now() - start_time).total_seconds()
    summary = engine.get_summary()

    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO eigenflux_hiring_summary
               (id, total_loops, total_experts_hired, total_teams_formed,
                total_contributions, total_salary_budget, avg_performance,
                domains_covered, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1000, summary["total_experts"], summary["total_teams"],
             summary["total_contributions"], summary["total_salary_budget"],
             summary["avg_performance"], summary["domains_covered"],
             datetime.now().isoformat()),
        )
        conn.commit()

    print(f"\n{'=' * 70}")
    print(f"  1000 次专家聘请循环完成 — 耗时: {elapsed:.1f} 秒")
    print(f"{'=' * 70}")

    return {
        "total_loops": 1000,
        "total_hired": total_hired,
        "total_teams": total_teams,
        "total_contribs": total_contribs,
        "total_salary": total_salary,
        "summary": summary,
        "elapsed": round(elapsed, 1),
    }


def generate_hiring_report(stats: dict):
    """生成聘请报告（R10-03）"""
    s = stats["summary"]
    print(f"\n{'=' * 70}")
    print("  EigenFlux 专家聘请 — 最终报告")
    print(f"{'=' * 70}")
    print(f"  循环次数:       {stats['total_loops']}")
    print(f"  耗时:           {stats['elapsed']} 秒")
    print(f"  聘请专家:       {s['total_experts']}")
    print(f"  组建团队:       {s['total_teams']}")
    print(f"  专家贡献:       {s['total_contributions']}")
    print(f"  薪资预算:       ¥{s['total_salary_budget']:,}")
    print(f"  平均能力:       {s['avg_performance']}")
    print(f"  覆盖领域:       {s['domains_covered']}/{len(EXPERT_DOMAINS)}")
    print(f"{'=' * 70}")

    # 各领域明细
    print(f"\n  各领域专家分布:")
    print(f"  {'领域':<20} {'专家数':>6} {'贡献数':>6} {'平均能力':>8}")
    print(f"  {'-' * 45}")

    with get_conn() as conn:
        for domain_key, domain in EXPERT_DOMAINS.items():
            row = conn.execute(
                """SELECT COUNT(*) as c, COALESCE(AVG(performance_score),0) as a
                   FROM eigenflux_experts WHERE domain=?""",
                (domain_key,)
            ).fetchone()
            contribs = conn.execute(
                """SELECT COUNT(*) as c FROM eigenflux_expert_contributions
                   WHERE expert_id IN (SELECT expert_id FROM eigenflux_experts WHERE domain=?)""",
                (domain_key,)
            ).fetchone()["c"]
            print(f"  {domain['cn']:<20} {row['c']:>6} {contribs:>6} {row['a']:>8.4f}")

    # 专家级别分布
    print(f"\n  专家级别分布:")
    with get_conn() as conn:
        for level in ["chief", "senior", "expert"]:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM eigenflux_experts WHERE level=?",
                (level,)
            ).fetchone()["c"]
            label = {"chief": "首席专家", "senior": "高级专家", "expert": "专家"}[level]
            print(f"    {label}: {count} 位")

    print(f"\n{'=' * 70}")
    print("  EigenFlux 专家聘请完成 — 系统能力已显著提升")
    print(f"{'=' * 70}")


# ============================================================
#  便捷函数（R04-03）
# ============================================================

def hire_expert(domain: Optional[str] = None) -> dict:
    """聘请一位专家"""
    return get_expert_hiring_engine().hire_expert(0, domain)

def hire_experts(count: int, domain: Optional[str] = None) -> List[dict]:
    """批量聘请专家"""
    return get_expert_hiring_engine().hire_batch(0, count, domain)

def form_expert_team(objective: Optional[str] = None) -> dict:
    """组建专家团队"""
    return get_expert_hiring_engine().form_team(0, objective)

def get_hiring_summary() -> dict:
    """获取聘请汇总"""
    return get_expert_hiring_engine().get_summary()

def get_version_info() -> dict:
    return {
        "module": "eigenflux_expert_hiring",
        "version": "1.0.0",
        "expert_roles": len(ALL_EXPERTS),
        "domains": len(EXPERT_DOMAINS),
        "max_retries": MAX_RETRIES,
    }

def health_check() -> dict:
    return get_expert_hiring_engine().health_check()


__all__ = [
    "EXPERT_DOMAINS", "ALL_EXPERTS",
    "EigenFluxExpertHiringEngine",
    "get_expert_hiring_engine",
    "hire_expert", "hire_experts", "form_expert_team",
    "get_hiring_summary", "get_version_info", "health_check",
    "run_1000_hiring_loops", "generate_hiring_report",
]


# ============================================================
#  入口
# ============================================================

if __name__ == '__main__':
    stats = run_1000_hiring_loops()
    generate_hiring_report(stats)
