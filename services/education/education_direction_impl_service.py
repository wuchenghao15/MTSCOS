#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 教育方向落实服务 (EducationDirectionImplService)
=====================================================

面向 MTSCOS 教育系统的三大教育方向（K12、成人教育、高等教育）提供
方向规划、配置落库与汇总统计能力，确保各类教育方向能够以结构化数据
沉淀并可被上层业务检索与追踪。

核心能力：
1. K12 教育方向
   - 小学：趣味化教学、游戏化学习、基础认知培养
   - 初中：知识点强化、学科衔接、学习方法指导
   - 高中：备考冲刺、选科指导、生涯规划
   - 家校协同、AI学情分析、自适应学习路径
2. 成人教育方向
   - 职业认证（教师资格、会计、建造师、护士执业等）
   - 技能图谱构建、学分银行、碎片化微课
   - 企业培训SaaS、学习社区
3. 高等教育方向
   - 高校教学融合、研究生备考、学术写作辅助
   - 产学研结合、AI科研助手
"""

import os
import sys
import json
import sqlite3
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

# ========== 项目根目录与数据库路径解析 ==========

# 本文件位于 <PROJECT_ROOT>/services/education/education_direction_impl_service.py
# 向上回溯三层即得到项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 确保项目根目录在 sys.path 中，便于直接以脚本方式运行
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    # 优先使用 core/db_path.py 统一解析规范数据库路径
    from core.db_path import get_db_path
    DATABASE_PATH = get_db_path('app.db')
except Exception as _db_path_err:  # noqa: BLE001
    # 解析失败时回退到项目根目录下的 app.db
    DATABASE_PATH = os.path.join(PROJECT_ROOT, 'app.db')

# ========== 日志配置 ==========

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'education_direction_impl_service.log'),
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ========== K12 学段配置 ==========

# K12 通用能力：所有学段共有的方向落实点
K12_COMMON_CAPABILITIES = ['家校协同', 'AI学情分析', '自适应学习路径']

K12_STAGE_CONFIG: Dict[str, Dict[str, Any]] = {
    'primary': {
        'stage_name': '小学',
        'features': ['趣味化教学', '游戏化学习', '基础认知培养'],
        'knowledge_graph_config': {
            'depth': 2,
            'node_levels': ['学科', '基础知识点'],
            'adaptive': True,
            'prerequisite_analysis': False,
        },
        'parent_portal_enabled': True,
        'ai_tutoring_enabled': True,
        'default_objectives': ['激发学习兴趣', '夯实基础知识', '培养良好学习习惯'],
        'default_milestones': ['入学学情评估', '期中能力诊断', '期末成长报告'],
    },
    'junior': {
        'stage_name': '初中',
        'features': ['知识点强化', '学科衔接', '学习方法指导'],
        'knowledge_graph_config': {
            'depth': 3,
            'node_levels': ['学科', '单元', '知识点'],
            'adaptive': True,
            'prerequisite_analysis': True,
        },
        'parent_portal_enabled': True,
        'ai_tutoring_enabled': True,
        'default_objectives': ['强化核心知识体系', '做好初高中衔接', '掌握高效学习方法'],
        'default_milestones': ['学科诊断', '阶段强化训练', '中考全真模拟', '中考冲刺'],
    },
    'senior': {
        'stage_name': '高中',
        'features': ['备考冲刺', '选科指导', '生涯规划'],
        'knowledge_graph_config': {
            'depth': 4,
            'node_levels': ['学科', '模块', '专题', '考点'],
            'adaptive': True,
            'prerequisite_analysis': True,
            'exam_oriented': True,
        },
        'parent_portal_enabled': True,
        'ai_tutoring_enabled': True,
        'default_objectives': ['高效备考冲刺', '科学选科组合', '明确生涯发展方向'],
        'default_milestones': ['选科规划', '一轮复习', '二轮专题突破', '三模冲刺', '高考'],
    },
}


# ========== 成人教育认证配置 ==========

# 成人教育通用能力
ADULT_COMMON_CAPABILITIES = ['技能图谱构建', '学分银行', '碎片化微课',
                             '企业培训SaaS', '学习社区']

ADULT_CERT_TYPES: Dict[str, Dict[str, str]] = {
    'teacher_qualification': {'cert_name': '教师资格', 'industry': '教育'},
    'accounting': {'cert_name': '会计职称', 'industry': '财务'},
    'constructor': {'cert_name': '建造师', 'industry': '建筑'},
    'nurse_practice': {'cert_name': '护士执业资格', 'industry': '医疗'},
    'legal_professional': {'cert_name': '法律职业资格', 'industry': '法律'},
    'cpa': {'cert_name': '注册会计师', 'industry': '财务'},
    'pharmacist': {'cert_name': '执业药师', 'industry': '医药'},
    'engineer': {'cert_name': '注册工程师', 'industry': '工程'},
}

# 默认技能图谱模板（按行业类别）
ADULT_DEFAULT_SKILL_TREE: Dict[str, List[Dict[str, Any]]] = {
    '教育': [
        {'node': '教育理论', 'children': ['教育学', '教育心理学']},
        {'node': '教学技能', 'children': ['教学设计', '课堂管理', '教学评价']},
        {'node': '学科素养', 'children': ['学科知识', '课程标准']},
    ],
    '财务': [
        {'node': '基础理论', 'children': ['会计基础', '财经法规']},
        {'node': '实务操作', 'children': ['账务处理', '税务申报', '财务报表']},
        {'node': '管理会计', 'children': ['成本管理', '预算编制']},
    ],
    '建筑': [
        {'node': '工程管理', 'children': ['施工组织', '进度控制', '质量安全']},
        {'node': '技术规范', 'children': ['建筑结构', '工程力学', '法规标准']},
        {'node': '经济法规', 'children': ['工程经济', '建设法规']},
    ],
    '医疗': [
        {'node': '基础医学', 'children': ['解剖学', '生理学', '药理学']},
        {'node': '临床护理', 'children': ['护理基础', '专科护理', '急救护理']},
        {'node': '法规伦理', 'children': ['医疗卫生法规', '护理伦理']},
    ],
}


# ========== 高等教育配置 ==========

# 高等教育通用能力
HIGHER_COMMON_CAPABILITIES = ['高校教学融合', '研究生备考', '学术写作辅助',
                              '产学研结合', 'AI科研助手']

HIGHER_EDU_TYPES: Dict[str, Dict[str, Any]] = {
    'comprehensive': {
        'name': '综合性大学',
        'features': ['学科齐全', '交叉培养', '通识与专业并重'],
    },
    'research': {
        'name': '研究型大学',
        'features': ['科研导向', '学术深耕', '创新人才培养'],
    },
    'applied': {
        'name': '应用型大学',
        'features': ['产教融合', '实践导向', '应用能力培养'],
    },
    'vocational': {
        'name': '职业本科',
        'features': ['技能本位', '岗位对接', '双证融通'],
    },
    'normal': {
        'name': '师范类院校',
        'features': ['教育特色', '师资培养', '教育实习'],
    },
}

# 高校教学融合默认模块
HIGHER_DEFAULT_COURSE_MGMT = ['课程资源管理', '混合式教学', '教学评价', '学分管理']
# 研究生备考默认模块
HIGHER_DEFAULT_RESEARCH_SUPPORT = ['研究生备考', '学术写作辅助', 'AI科研助手', '文献检索']
# 论文辅助默认模块
HIGHER_DEFAULT_THESIS_ASSIST = ['选题指导', '文献综述', '论文润色', '查重检测']
# 产学研默认模块
HIGHER_DEFAULT_INTERNSHIP = ['产学研结合', '实习实训', '项目实践', '就业对接']


# ========== 计划状态与优先级枚举 ==========

VALID_PLAN_STATUS = {'planning', 'active', 'in_progress', 'completed', 'suspended', 'archived'}
VALID_PRIORITY = {'low', 'medium', 'high', 'urgent'}
VALID_DIRECTION_TYPES = {'k12', 'adult', 'higher'}


class EducationDirectionImplService:
    """教育方向落实服务：负责三大教育方向计划的创建、配置落库与统计。"""

    def __init__(self, db_path: Optional[str] = None):
        # 允许调用方注入自定义数据库路径，默认使用模块级解析的 DATABASE_PATH
        self.db_path = db_path or DATABASE_PATH
        self._lock = threading.RLock()
        # 初始化所有数据表
        self.init_tables()

    # ========== 数据库连接与初始化 ==========

    def _get_connection(self) -> sqlite3.Connection:
        """获取 sqlite3 连接，自动创建数据库文件所在目录。"""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def init_tables(self) -> Dict[str, Any]:
        """初始化所有教育方向相关数据表（幂等操作）。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()

                    # 教育方向计划表：统一存储 K12/成人/高教 三类计划
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS education_direction_plans (
                            id TEXT PRIMARY KEY,
                            direction_type TEXT NOT NULL,
                            plan_name TEXT NOT NULL,
                            description TEXT,
                            objectives TEXT,
                            milestones TEXT,
                            status TEXT DEFAULT 'planning',
                            priority TEXT DEFAULT 'medium',
                            created_at TEXT,
                            updated_at TEXT
                        )
                    ''')

                    # K12 学段配置表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS education_k12_stages (
                            id TEXT PRIMARY KEY,
                            stage TEXT NOT NULL,
                            stage_name TEXT,
                            features TEXT,
                            knowledge_graph_config TEXT,
                            parent_portal_enabled INTEGER DEFAULT 1,
                            ai_tutoring_enabled INTEGER DEFAULT 1,
                            created_at TEXT
                        )
                    ''')

                    # 成人教育认证表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS education_adult_certs (
                            id TEXT PRIMARY KEY,
                            cert_name TEXT NOT NULL,
                            cert_type TEXT,
                            industry TEXT,
                            exam_subjects TEXT,
                            skill_tree TEXT,
                            credit_bank_enabled INTEGER DEFAULT 1,
                            created_at TEXT
                        )
                    ''')

                    # 高等教育配置表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS education_higher_edu (
                            id TEXT PRIMARY KEY,
                            university_type TEXT NOT NULL,
                            course_management TEXT,
                            research_support TEXT,
                            thesis_assist TEXT,
                            internship_integration TEXT,
                            created_at TEXT
                        )
                    ''')

                    conn.commit()
                    logger.info('教育方向落实服务数据表初始化完成')
                    return {'success': True, 'message': '数据表初始化完成'}
        except Exception as e:
            logger.error(f'数据表初始化失败: {e}')
            return {'success': False, 'error': str(e)}

    # ========== K12 教育方向 ==========

    def create_k12_plan(self, stage: str, plan_name: str,
                        objectives: Optional[List[str]] = None,
                        milestones: Optional[List[str]] = None) -> Dict[str, Any]:
        """创建 K12 教育计划，同时落库对应学段配置。

        :param stage: 学段 primary/junior/senior
        :param plan_name: 计划名称
        :param objectives: 培养目标列表，为空时使用学段默认目标
        :param milestones: 里程碑列表，为空时使用学段默认里程碑
        """
        try:
            if stage not in K12_STAGE_CONFIG:
                return {'success': False,
                        'error': f'不支持的K12学段: {stage}，可选: {list(K12_STAGE_CONFIG.keys())}'}
            config = K12_STAGE_CONFIG[stage]

            # 合并默认能力与学段特性
            features = list(config['features']) + list(K12_COMMON_CAPABILITIES)
            final_objectives = list(objectives) if objectives else list(config['default_objectives'])
            final_milestones = list(milestones) if milestones else list(config['default_milestones'])
            description = f"K12-{config['stage_name']}教育方向落实计划"

            plan_id = f"k12_{uuid.uuid4().hex[:12]}"
            stage_id = f"stage_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()

            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO education_direction_plans
                            (id, direction_type, plan_name, description, objectives,
                             milestones, status, priority, created_at, updated_at)
                        VALUES (?, 'k12', ?, ?, ?, ?, 'planning', 'high', ?, ?)
                    ''', (plan_id, plan_name, description,
                          json.dumps(final_objectives, ensure_ascii=False),
                          json.dumps(final_milestones, ensure_ascii=False),
                          now, now))

                    cursor.execute('''
                        INSERT INTO education_k12_stages
                            (id, stage, stage_name, features, knowledge_graph_config,
                             parent_portal_enabled, ai_tutoring_enabled, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (stage_id, stage, config['stage_name'],
                          json.dumps(features, ensure_ascii=False),
                          json.dumps(config['knowledge_graph_config'], ensure_ascii=False),
                          1 if config['parent_portal_enabled'] else 0,
                          1 if config['ai_tutoring_enabled'] else 0,
                          now))

                    conn.commit()
                    logger.info(f'创建K12教育计划: {plan_name} ({plan_id}) 学段={stage}')
                    return {
                        'success': True,
                        'plan_id': plan_id,
                        'stage_id': stage_id,
                        'direction_type': 'k12',
                        'stage': stage,
                        'stage_name': config['stage_name'],
                        'features': features,
                        'objectives': final_objectives,
                        'milestones': final_milestones,
                        'knowledge_graph_config': config['knowledge_graph_config'],
                        'parent_portal_enabled': config['parent_portal_enabled'],
                        'ai_tutoring_enabled': config['ai_tutoring_enabled'],
                    }
        except Exception as e:
            logger.error(f'创建K12教育计划失败: {e}')
            return {'success': False, 'error': str(e)}

    # ========== 成人教育方向 ==========

    def create_adult_cert_plan(self, cert_name: str, industry: str,
                               exam_subjects: Optional[List[str]] = None,
                               skill_tree: Optional[Any] = None) -> Dict[str, Any]:
        """创建成人教育认证计划，同时落库认证配置。

        :param cert_name: 认证名称（如：教师资格、建造师）
        :param industry: 所属行业（如：教育、建筑、医疗）
        :param exam_subjects: 考试科目列表
        :param skill_tree: 技能图谱（dict 或 list），为空时按行业取默认模板
        """
        try:
            if not cert_name:
                return {'success': False, 'error': '认证名称不能为空'}

            # 尝试根据 cert_name 匹配预设认证类型
            cert_type = 'custom'
            for ckey, cval in ADULT_CERT_TYPES.items():
                if cval['cert_name'] in cert_name or cert_name in cval['cert_name']:
                    cert_type = ckey
                    if not industry:
                        industry = cval['industry']
                    break

            final_exam_subjects = list(exam_subjects) if exam_subjects else ['综合能力', '专业知识', '实务操作']
            # 技能图谱：优先使用传入值，其次取行业默认模板
            if skill_tree is not None:
                final_skill_tree = skill_tree
            else:
                final_skill_tree = ADULT_DEFAULT_SKILL_TREE.get(industry, [
                    {'node': '基础理论', 'children': []},
                    {'node': '专业技能', 'children': []},
                    {'node': '综合实务', 'children': []},
                ])

            # 能力点作为目标，里程碑按备考阶段设计
            objectives = list(ADULT_COMMON_CAPABILITIES)
            milestones = ['基础阶段学习', '强化训练', '模拟考试', '考前冲刺', '认证考试']

            plan_id = f"adult_{uuid.uuid4().hex[:12]}"
            cert_id = f"cert_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()
            description = f"成人教育-{cert_name}认证方向落实计划"

            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO education_direction_plans
                            (id, direction_type, plan_name, description, objectives,
                             milestones, status, priority, created_at, updated_at)
                        VALUES (?, 'adult', ?, ?, ?, ?, 'planning', 'medium', ?, ?)
                    ''', (plan_id, f"{cert_name}认证计划", description,
                          json.dumps(objectives, ensure_ascii=False),
                          json.dumps(milestones, ensure_ascii=False),
                          now, now))

                    cursor.execute('''
                        INSERT INTO education_adult_certs
                            (id, cert_name, cert_type, industry, exam_subjects,
                             skill_tree, credit_bank_enabled, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ''', (cert_id, cert_name, cert_type, industry,
                          json.dumps(final_exam_subjects, ensure_ascii=False),
                          json.dumps(final_skill_tree, ensure_ascii=False),
                          now))

                    conn.commit()
                    logger.info(f'创建成人教育认证计划: {cert_name} ({plan_id}) 行业={industry}')
                    return {
                        'success': True,
                        'plan_id': plan_id,
                        'cert_id': cert_id,
                        'direction_type': 'adult',
                        'cert_name': cert_name,
                        'cert_type': cert_type,
                        'industry': industry,
                        'exam_subjects': final_exam_subjects,
                        'skill_tree': final_skill_tree,
                        'credit_bank_enabled': True,
                        'capabilities': objectives,
                        'milestones': milestones,
                    }
        except Exception as e:
            logger.error(f'创建成人教育认证计划失败: {e}')
            return {'success': False, 'error': str(e)}

    # ========== 高等教育方向 ==========

    def create_higher_edu_plan(self, university_type: str,
                               features: Optional[Union[List[str], Dict[str, Any]]] = None
                               ) -> Dict[str, Any]:
        """创建高等教育计划，同时落库高校配置。

        :param university_type: 高校类型（comprehensive/research/applied/vocational/normal）
        :param features: 特色能力，可为列表或字典；为空时使用类型默认 + 通用能力
        """
        try:
            if university_type not in HIGHER_EDU_TYPES:
                return {'success': False,
                        'error': f'不支持的高校类型: {university_type}，可选: {list(HIGHER_EDU_TYPES.keys())}'}
            type_config = HIGHER_EDU_TYPES[university_type]

            # 组装特色能力
            if features is None:
                feature_list = list(type_config['features']) + list(HIGHER_COMMON_CAPABILITIES)
            elif isinstance(features, dict):
                feature_list = list(features.get('features', type_config['features'])) + list(HIGHER_COMMON_CAPABILITIES)
            else:
                feature_list = list(features) + list(HIGHER_COMMON_CAPABILITIES)

            objectives = feature_list
            milestones = ['培养方案制定', '课程资源建设', '教学融合实施', '科研支持落地', '产学研评估']
            description = f"高等教育-{type_config['name']}方向落实计划"

            plan_id = f"higher_{uuid.uuid4().hex[:12]}"
            higher_id = f"hedu_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()

            course_mgmt = list(HIGHER_DEFAULT_COURSE_MGMT)
            research_support = list(HIGHER_DEFAULT_RESEARCH_SUPPORT)
            thesis_assist = list(HIGHER_DEFAULT_THESIS_ASSIST)
            internship = list(HIGHER_DEFAULT_INTERNSHIP)

            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO education_direction_plans
                            (id, direction_type, plan_name, description, objectives,
                             milestones, status, priority, created_at, updated_at)
                        VALUES (?, 'higher', ?, ?, ?, ?, 'planning', 'medium', ?, ?)
                    ''', (plan_id, f"{type_config['name']}教育计划", description,
                          json.dumps(objectives, ensure_ascii=False),
                          json.dumps(milestones, ensure_ascii=False),
                          now, now))

                    cursor.execute('''
                        INSERT INTO education_higher_edu
                            (id, university_type, course_management, research_support,
                             thesis_assist, internship_integration, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (higher_id, university_type,
                          json.dumps(course_mgmt, ensure_ascii=False),
                          json.dumps(research_support, ensure_ascii=False),
                          json.dumps(thesis_assist, ensure_ascii=False),
                          json.dumps(internship, ensure_ascii=False),
                          now))

                    conn.commit()
                    logger.info(f'创建高等教育计划: {type_config["name"]} ({plan_id})')
                    return {
                        'success': True,
                        'plan_id': plan_id,
                        'higher_edu_id': higher_id,
                        'direction_type': 'higher',
                        'university_type': university_type,
                        'university_type_name': type_config['name'],
                        'features': feature_list,
                        'objectives': objectives,
                        'milestones': milestones,
                        'course_management': course_mgmt,
                        'research_support': research_support,
                        'thesis_assist': thesis_assist,
                        'internship_integration': internship,
                    }
        except Exception as e:
            logger.error(f'创建高等教育计划失败: {e}')
            return {'success': False, 'error': str(e)}

    # ========== 计划查询与维护 ==========

    def get_all_plans(self) -> Dict[str, Any]:
        """获取所有教育方向计划。"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, direction_type, plan_name, description, objectives,
                           milestones, status, priority, created_at, updated_at
                    FROM education_direction_plans
                    ORDER BY created_at DESC
                ''')
                rows = cursor.fetchall()
                plans = [self._row_to_plan(r) for r in rows]
                return {'success': True, 'plans': plans, 'total': len(plans)}
        except Exception as e:
            logger.error(f'获取所有计划失败: {e}')
            return {'success': False, 'error': str(e)}

    def get_plans_by_type(self, direction_type: str) -> Dict[str, Any]:
        """按方向类型获取计划（k12/adult/higher）。"""
        try:
            if direction_type not in VALID_DIRECTION_TYPES:
                return {'success': False,
                        'error': f'不支持的方向类型: {direction_type}，可选: {sorted(VALID_DIRECTION_TYPES)}'}
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, direction_type, plan_name, description, objectives,
                           milestones, status, priority, created_at, updated_at
                    FROM education_direction_plans
                    WHERE direction_type = ?
                    ORDER BY created_at DESC
                ''', (direction_type,))
                rows = cursor.fetchall()
                plans = [self._row_to_plan(r) for r in rows]
                return {'success': True, 'direction_type': direction_type,
                        'plans': plans, 'total': len(plans)}
        except Exception as e:
            logger.error(f'按类型获取计划失败: {e}')
            return {'success': False, 'error': str(e)}

    def update_plan_status(self, plan_id: str, status: str) -> Dict[str, Any]:
        """更新计划状态。"""
        try:
            if status not in VALID_PLAN_STATUS:
                return {'success': False,
                        'error': f'无效的计划状态: {status}，可选: {sorted(VALID_PLAN_STATUS)}'}
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE education_direction_plans
                        SET status = ?, updated_at = ?
                        WHERE id = ?
                    ''', (status, now, plan_id))
                    if cursor.rowcount > 0:
                        conn.commit()
                        logger.info(f'更新计划状态: {plan_id} -> {status}')
                        return {'success': True, 'plan_id': plan_id, 'status': status}
                    return {'success': False, 'error': '计划不存在或状态未变更'}
        except Exception as e:
            logger.error(f'更新计划状态失败: {e}')
            return {'success': False, 'error': str(e)}

    def get_direction_summary(self) -> Dict[str, Any]:
        """获取教育方向汇总统计：计划总数、按类型/状态分布、各配置表数量。"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # 计划总数
                cursor.execute('SELECT COUNT(*) AS cnt FROM education_direction_plans')
                total_plans = cursor.fetchone()['cnt']

                # 按方向类型统计
                cursor.execute('''
                    SELECT direction_type, COUNT(*) AS cnt
                    FROM education_direction_plans
                    GROUP BY direction_type
                ''')
                by_type = {row['direction_type']: row['cnt'] for row in cursor.fetchall()}

                # 按状态统计
                cursor.execute('''
                    SELECT status, COUNT(*) AS cnt
                    FROM education_direction_plans
                    GROUP BY status
                ''')
                by_status = {row['status']: row['cnt'] for row in cursor.fetchall()}

                # 各配置表记录数
                cursor.execute('SELECT COUNT(*) AS cnt FROM education_k12_stages')
                k12_stage_count = cursor.fetchone()['cnt']
                cursor.execute('SELECT COUNT(*) AS cnt FROM education_adult_certs')
                adult_cert_count = cursor.fetchone()['cnt']
                cursor.execute('SELECT COUNT(*) AS cnt FROM education_higher_edu')
                higher_edu_count = cursor.fetchone()['cnt']

                # 各方向计划数（确保三个方向都有键，便于上层渲染）
                type_counts = {
                    'k12': by_type.get('k12', 0),
                    'adult': by_type.get('adult', 0),
                    'higher': by_type.get('higher', 0),
                }

                summary = {
                    'total_plans': total_plans,
                    'by_direction_type': type_counts,
                    'by_status': by_status,
                    'k12_stage_configs': k12_stage_count,
                    'adult_cert_configs': adult_cert_count,
                    'higher_edu_configs': higher_edu_count,
                    'supported_directions': sorted(VALID_DIRECTION_TYPES),
                    'supported_k12_stages': sorted(K12_STAGE_CONFIG.keys()),
                }
                return {'success': True, 'summary': summary}
        except Exception as e:
            logger.error(f'获取方向汇总统计失败: {e}')
            return {'success': False, 'error': str(e)}

    # ========== 内部工具方法 ==========

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为计划字典，反序列化 JSON 字段。"""
        plan = {
            'id': row['id'],
            'direction_type': row['direction_type'],
            'plan_name': row['plan_name'],
            'description': row['description'],
            'status': row['status'],
            'priority': row['priority'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }
        # 反序列化 objectives / milestones
        for field in ('objectives', 'milestones'):
            raw = row[field]
            if raw:
                try:
                    plan[field] = json.loads(raw)
                except (ValueError, TypeError):
                    plan[field] = raw
            else:
                plan[field] = []
        return plan


# ========== 直接运行入口（冒烟测试） ==========

if __name__ == '__main__':
    service = EducationDirectionImplService()

    print('\n===== 1. 初始化数据表 =====')
    print(service.init_tables())

    print('\n===== 2. 创建 K12 计划 =====')
    print(service.create_k12_plan('primary', '小学趣味化教学计划'))
    print(service.create_k12_plan('senior', '高三备考冲刺计划',
                                  objectives=['高考提分', '志愿填报指导'],
                                  milestones=['一模', '二模', '高考']))

    print('\n===== 3. 创建成人教育认证计划 =====')
    print(service.create_adult_cert_plan('教师资格', '教育',
                                         exam_subjects=['综合素质', '教育知识与能力', '面试']))
    print(service.create_adult_cert_plan('建造师', '建筑'))

    print('\n===== 4. 创建高等教育计划 =====')
    print(service.create_higher_edu_plan('research'))
    print(service.create_higher_edu_plan('applied', features=['产教融合', '岗位实训']))

    print('\n===== 5. 获取所有计划 =====')
    all_plans = service.get_all_plans()
    print(f"总数: {all_plans.get('total')}")
    for p in all_plans.get('plans', []):
        print(f"  - [{p['direction_type']}] {p['plan_name']} ({p['status']})")

    print('\n===== 6. 按类型获取计划 (k12) =====')
    k12_plans = service.get_plans_by_type('k12')
    print(f"K12 计划数: {k12_plans.get('total')}")

    print('\n===== 7. 更新计划状态 =====')
    if all_plans.get('plans'):
        first_id = all_plans['plans'][0]['id']
        print(service.update_plan_status(first_id, 'active'))

    print('\n===== 8. 方向汇总统计 =====')
    print(service.get_direction_summary())
