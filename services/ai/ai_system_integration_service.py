#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS AI 系统融合适配服务
==========================
提供 AI 员工角色管理、AI 集群团队组建、AI 引擎注册与模型路由、
AI 协作日志、知识脑库同步、AI 治理规则与行为审计等融合能力。

核心能力：
1. AI 员工角色 - 角色注册、晋升/降级、绩效考核
2. AI 集群团队 - 动态组队、集体智能、AI 阵列
3. AI 引擎注册 - 多引擎统一注册与模型路由
4. AI 协作日志 - 多 AI 协作过程记录与评分
5. 知识脑库同步 - 跨区域知识贡献与同步统计
6. AI 治理规则 - 审计/伦理/边界/可解释性规则与行为审计
"""

import os
import json
import uuid
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------- 数据库路径解析（失败兜底到 PROJECT_ROOT/app.db）----------
try:
    from core.db_path import get_db_path as _mtscos_get_db_path
    DATABASE_PATH = _mtscos_get_db_path('app.db')
except Exception:
    # 项目根目录：services/ai/xxx.py 向上三级
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATABASE_PATH = os.path.join(PROJECT_ROOT, 'app.db')

# ---------- 常量定义 ----------
# AI 角色类型（角色编码 -> 中文名称）
AI_ROLE_TYPES = {
    'exam_grader': '考试评分员',
    'question_curator': '题库管理员',
    'learning_analyst': '学情分析师',
    'counselor': '心理咨询师',
    'curriculum_designer': '课程设计师',
    'security_auditor': '安全审计员',
    'auto_repairer': '自修复工程师',
    'knowledge_manager': '知识管理员',
}

# AI 员工等级（由低到高）
AI_LEVELS = ['min', 'junior', 'mid', 'senior', 'expert', 'master']

# AI 治理规则类型
AI_RULE_TYPES = ['audit', 'ethics', 'boundary', 'explainability']

# AI 集群组建策略
AI_CLUSTER_STRATEGIES = {
    'dynamic_team': '动态组队：根据任务需求自动组建最优 AI 团队',
    'collective_intelligence': '集体智能：多 AI 投票决策、对抗辩论',
    'ai_array': 'AI 阵列：同类型 AI 并行处理',
}

# 任务类型到偏好引擎类型映射（用于模型路由）
TASK_ENGINE_PREFERENCE = {
    'grading': ['exam', 'assessment', 'scoring'],
    'question_generation': ['generation', 'content', 'nlp'],
    'learning_analysis': ['analysis', 'analytics', 'data'],
    'counseling': ['dialogue', 'nlp', 'chat'],
    'curriculum_design': ['generation', 'planning', 'nlp'],
    'security_audit': ['security', 'analysis', 'audit'],
    'auto_repair': ['repair', 'ops', 'engineering'],
    'knowledge_management': ['retrieval', 'nlp', 'knowledge'],
}


class AISystemIntegrationService:
    """AI 系统融合适配服务"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_PATH
        self._lock = threading.RLock()
        self.init_tables()

    # ---------- 基础设施 ----------
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接，自动创建父目录"""
        dir_name = os.path.dirname(os.path.abspath(self.db_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def init_tables(self) -> Dict[str, Any]:
        """初始化全部数据表"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    # AI 员工角色配置
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_employee_roles (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            role_code TEXT NOT NULL UNIQUE,
                            role_name TEXT NOT NULL,
                            specialization TEXT,
                            capabilities TEXT,
                            level TEXT DEFAULT 'junior',
                            performance_score REAL DEFAULT 0.0,
                            tasks_completed INTEGER DEFAULT 0,
                            accuracy_rate REAL DEFAULT 0.0,
                            created_at TEXT
                        )
                    ''')
                    # AI 集群团队
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_cluster_teams (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            team_id TEXT NOT NULL UNIQUE,
                            team_name TEXT NOT NULL,
                            purpose TEXT,
                            member_ids TEXT,
                            leader_id TEXT,
                            formation_strategy TEXT,
                            status TEXT DEFAULT 'active',
                            created_at TEXT
                        )
                    ''')
                    # AI 引擎注册表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_engine_registry (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            engine_id TEXT NOT NULL UNIQUE,
                            engine_name TEXT NOT NULL,
                            engine_type TEXT,
                            model_name TEXT,
                            input_format TEXT,
                            output_format TEXT,
                            is_active INTEGER DEFAULT 1,
                            performance_metrics TEXT,
                            created_at TEXT
                        )
                    ''')
                    # AI 协作日志
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_collaboration_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            from_agent TEXT,
                            to_agent TEXT,
                            task_type TEXT,
                            content TEXT,
                            result TEXT,
                            collaboration_score REAL DEFAULT 0.0,
                            timestamp TEXT
                        )
                    ''')
                    # 知识脑库同步
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_knowledge_brain_sync (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            brain_region TEXT,
                            knowledge_type TEXT,
                            sync_count INTEGER DEFAULT 0,
                            last_sync TEXT,
                            contributors TEXT,
                            created_at TEXT
                        )
                    ''')
                    # AI 治理规则
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS ai_governance_rules (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            rule_name TEXT NOT NULL,
                            rule_type TEXT,
                            rule_content TEXT,
                            enforcement_level TEXT DEFAULT 'medium',
                            created_at TEXT
                        )
                    ''')
                    # 常用索引
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_roles_level ON ai_employee_roles(level)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_teams_status ON ai_cluster_teams(status)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_engines_active ON ai_engine_registry(is_active)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_collab_ts ON ai_collaboration_log(timestamp)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_governance_type ON ai_governance_rules(rule_type)')
                    conn.commit()
            logger.info('AI 系统融合适配服务数据表初始化完成')
            return {'success': True, 'message': '数据表初始化完成'}
        except Exception as e:
            logger.error('数据表初始化失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI 员工角色 ----------
    def register_ai_role(self, role_code: str, role_name: str,
                         specialization: str, capabilities: Any,
                         level: str = 'junior') -> Dict[str, Any]:
        """注册 AI 员工角色（已存在则更新基本信息，保留绩效与任务统计）"""
        try:
            if level not in AI_LEVELS:
                return {'success': False, 'error': f'非法等级，可选: {AI_LEVELS}'}
            if isinstance(capabilities, (list, dict)):
                capabilities_str = json.dumps(capabilities, ensure_ascii=False)
            else:
                capabilities_str = str(capabilities)
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT role_code FROM ai_employee_roles WHERE role_code = ?', (role_code,))
                    exists = cursor.fetchone()
                    if exists:
                        cursor.execute('''
                            UPDATE ai_employee_roles
                            SET role_name = ?, specialization = ?, capabilities = ?, level = ?
                            WHERE role_code = ?
                        ''', (role_name, specialization, capabilities_str, level, role_code))
                    else:
                        cursor.execute('''
                            INSERT INTO ai_employee_roles
                                (role_code, role_name, specialization, capabilities, level,
                                 performance_score, tasks_completed, accuracy_rate, created_at)
                            VALUES (?, ?, ?, ?, ?, 0.0, 0, 0.0, ?)
                        ''', (role_code, role_name, specialization, capabilities_str, level, now))
                    conn.commit()
            logger.info('注册 AI 员工角色: %s (%s)', role_name, role_code)
            return {
                'success': True,
                'role_code': role_code,
                'role_name': role_name,
                'level': level,
                'message': 'AI 员工角色注册成功',
            }
        except Exception as e:
            logger.error('注册 AI 员工角色失败: %s', e)
            return {'success': False, 'error': str(e)}

    def promote_ai_employee(self, role_code: str, new_level: str) -> Dict[str, Any]:
        """AI 员工晋升/降级"""
        try:
            if new_level not in AI_LEVELS:
                return {'success': False, 'error': f'非法等级，可选: {AI_LEVELS}'}
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT level FROM ai_employee_roles WHERE role_code = ?', (role_code,))
                    row = cursor.fetchone()
                    if not row:
                        return {'success': False, 'error': '角色不存在'}
                    old_level = row[0]
                    cursor.execute('UPDATE ai_employee_roles SET level = ? WHERE role_code = ?',
                                   (new_level, role_code))
                    conn.commit()
            direction = '晋升' if AI_LEVELS.index(new_level) > AI_LEVELS.index(old_level) else '降级'
            logger.info('AI 员工 %s 由 %s %s 至 %s', role_code, old_level, direction, new_level)
            return {
                'success': True,
                'role_code': role_code,
                'old_level': old_level,
                'new_level': new_level,
                'direction': direction,
                'message': f'AI 员工{direction}成功',
            }
        except Exception as e:
            logger.error('AI 员工升降级失败: %s', e)
            return {'success': False, 'error': str(e)}

    def evaluate_performance(self, role_code: str) -> Dict[str, Any]:
        """绩效考核：综合任务量与准确率计算绩效分"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT role_code, role_name, level, tasks_completed, accuracy_rate, performance_score
                        FROM ai_employee_roles WHERE role_code = ?
                    ''', (role_code,))
                    row = cursor.fetchone()
                    if not row:
                        return {'success': False, 'error': '角色不存在'}
                    role_name = row['role_name']
                    level = row['level'] or 'junior'
                    tasks = row['tasks_completed'] or 0
                    accuracy = row['accuracy_rate'] or 0.0
                    # 绩效分 = 准确率*70% + 任务饱和度*30%（饱和度按 100 任务封顶）
                    saturation = min(tasks / 100.0, 1.0)
                    performance_score = round(accuracy * 0.7 * 100 + saturation * 0.3 * 100, 2)
                    cursor.execute('UPDATE ai_employee_roles SET performance_score = ? WHERE role_code = ?',
                                   (performance_score, role_code))
                    conn.commit()
            # 绩效驱动的晋升/降级建议
            suggestion = None
            current_idx = AI_LEVELS.index(level) if level in AI_LEVELS else 0
            if performance_score >= 90 and current_idx < len(AI_LEVELS) - 1:
                suggestion = f'绩效优秀，建议晋升至 {AI_LEVELS[current_idx + 1]}'
            elif performance_score < 50 and current_idx > 0:
                suggestion = f'绩效偏低，建议降级至 {AI_LEVELS[current_idx - 1]}'
            logger.info('AI 员工 %s 绩效考核完成: %.2f', role_code, performance_score)
            return {
                'success': True,
                'role_code': role_code,
                'role_name': role_name,
                'level': level,
                'tasks_completed': tasks,
                'accuracy_rate': accuracy,
                'performance_score': performance_score,
                'promotion_suggestion': suggestion,
            }
        except Exception as e:
            logger.error('绩效考核失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI 集群团队 ----------
    def form_ai_team(self, purpose: str, required_roles: List[str],
                     strategy: str = 'dynamic_team') -> Dict[str, Any]:
        """动态组建 AI 团队（按所需角色挑选成员，选等级/绩效最高者为队长）"""
        try:
            if strategy not in AI_CLUSTER_STRATEGIES:
                return {'success': False, 'error': f'非法策略，可选: {list(AI_CLUSTER_STRATEGIES.keys())}'}
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    members = []
                    for role_code in required_roles:
                        cursor.execute('''
                            SELECT role_code, role_name, level, performance_score
                            FROM ai_employee_roles
                            WHERE role_code = ? OR specialization LIKE ?
                            ORDER BY performance_score DESC LIMIT 1
                        ''', (role_code, f'%{role_code}%'))
                        row = cursor.fetchone()
                        if row:
                            members.append(dict(row))
                    if not members:
                        return {'success': False, 'error': '未找到匹配所需角色的 AI 员工'}
                    # 队长：等级最高，其次绩效最高
                    members.sort(
                        key=lambda m: (AI_LEVELS.index(m['level']) if m['level'] in AI_LEVELS else 0,
                                       m['performance_score'] or 0.0),
                        reverse=True,
                    )
                    leader = members[0]
                    team_id = f"team_{uuid.uuid4().hex[:12]}"
                    team_name = f"AI团队-{purpose[:20]}"
                    member_ids = [m['role_code'] for m in members]
                    now = datetime.now().isoformat()
                    cursor.execute('''
                        INSERT INTO ai_cluster_teams
                            (team_id, team_name, purpose, member_ids, leader_id,
                             formation_strategy, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                    ''', (team_id, team_name, purpose, json.dumps(member_ids, ensure_ascii=False),
                          leader['role_code'], strategy, now))
                    conn.commit()
            logger.info('组建 AI 团队 %s（策略=%s，成员=%d）', team_id, strategy, len(members))
            return {
                'success': True,
                'team_id': team_id,
                'team_name': team_name,
                'purpose': purpose,
                'formation_strategy': strategy,
                'strategy_desc': AI_CLUSTER_STRATEGIES[strategy],
                'leader_id': leader['role_code'],
                'members': member_ids,
                'member_count': len(members),
                'message': 'AI 团队组建成功',
            }
        except Exception as e:
            logger.error('组建 AI 团队失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI 引擎注册与路由 ----------
    def register_ai_engine(self, engine_name: str, engine_type: str,
                           model_name: str, input_format: str,
                           output_format: str) -> Dict[str, Any]:
        """注册 AI 引擎"""
        try:
            engine_id = f"engine_{uuid.uuid4().hex[:12]}"
            metrics = {'score': 0.5, 'latency_ms': 0, 'throughput': 0}
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO ai_engine_registry
                            (engine_id, engine_name, engine_type, model_name,
                             input_format, output_format, is_active, performance_metrics, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ''', (engine_id, engine_name, engine_type, model_name,
                          input_format, output_format, json.dumps(metrics), now))
                    conn.commit()
            logger.info('注册 AI 引擎: %s (%s)', engine_name, engine_id)
            return {
                'success': True,
                'engine_id': engine_id,
                'engine_name': engine_name,
                'engine_type': engine_type,
                'model_name': model_name,
                'message': 'AI 引擎注册成功',
            }
        except Exception as e:
            logger.error('注册 AI 引擎失败: %s', e)
            return {'success': False, 'error': str(e)}

    def route_to_engine(self, task_type: str, input_data: Any) -> Dict[str, Any]:
        """模型路由：根据任务类型选择最优引擎（偏好类型匹配 + 性能分排序）"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM ai_engine_registry WHERE is_active = 1')
                    rows = cursor.fetchall()
                    if not rows:
                        return {'success': False, 'error': '无可用 AI 引擎'}
                    engines = []
                    for r in rows:
                        try:
                            metrics = json.loads(r['performance_metrics']) if r['performance_metrics'] else {}
                        except Exception:
                            metrics = {}
                        engines.append({
                            'engine_id': r['engine_id'],
                            'engine_name': r['engine_name'],
                            'engine_type': r['engine_type'] or '',
                            'model_name': r['model_name'],
                            'score': float(metrics.get('score', 0.5)),
                            'metrics': metrics,
                        })
            preferred = TASK_ENGINE_PREFERENCE.get(task_type, [])
            # 优先匹配偏好引擎类型，若无匹配则全部参与排序
            if preferred:
                matched = [e for e in engines if e['engine_type'] in preferred]
                candidates = matched if matched else engines
            else:
                candidates = engines
            candidates.sort(key=lambda e: e['score'], reverse=True)
            best = candidates[0]
            logger.info('任务 %s 路由至引擎 %s（得分=%.2f）', task_type, best['engine_name'], best['score'])
            return {
                'success': True,
                'task_type': task_type,
                'engine_id': best['engine_id'],
                'engine_name': best['engine_name'],
                'engine_type': best['engine_type'],
                'model_name': best['model_name'],
                'performance_score': best['score'],
                'input_data': input_data,
                'message': '模型路由成功',
            }
        except Exception as e:
            logger.error('模型路由失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI 协作日志 ----------
    def log_collaboration(self, from_agent: str, to_agent: str,
                          task_type: str, content: str,
                          result: str, score: float = 0.0) -> Dict[str, Any]:
        """记录 AI 协作"""
        try:
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO ai_collaboration_log
                            (from_agent, to_agent, task_type, content, result,
                             collaboration_score, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (from_agent, to_agent, task_type, content, result, float(score), now))
                    conn.commit()
            logger.info('记录 AI 协作: %s -> %s（评分=%.2f）', from_agent, to_agent, score)
            return {
                'success': True,
                'from_agent': from_agent,
                'to_agent': to_agent,
                'task_type': task_type,
                'collaboration_score': score,
                'timestamp': now,
                'message': 'AI 协作记录成功',
            }
        except Exception as e:
            logger.error('记录 AI 协作失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 知识脑库同步 ----------
    def sync_knowledge_brain(self, brain_region: str, knowledge_type: str,
                             contributors: Any) -> Dict[str, Any]:
        """知识脑库同步（已存在则累加同步次数并合并贡献者）"""
        try:
            if isinstance(contributors, (list, dict)):
                contrib_list = list(contributors.values()) if isinstance(contributors, dict) else list(contributors)
            else:
                contrib_list = [str(contributors)]
            contrib_list = [str(c) for c in contrib_list]
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT id, sync_count, contributors FROM ai_knowledge_brain_sync
                        WHERE brain_region = ? AND knowledge_type = ?
                    ''', (brain_region, knowledge_type))
                    row = cursor.fetchone()
                    if row:
                        try:
                            existing = set(json.loads(row['contributors'])) if row['contributors'] else set()
                        except Exception:
                            existing = set()
                        merged = sorted(existing.union(set(contrib_list)))
                        new_count = (row['sync_count'] or 0) + 1
                        cursor.execute('''
                            UPDATE ai_knowledge_brain_sync
                            SET sync_count = ?, last_sync = ?, contributors = ?
                            WHERE id = ?
                        ''', (new_count, now, json.dumps(merged, ensure_ascii=False), row['id']))
                        conn.commit()
                        sync_count = new_count
                        contributors_out = merged
                    else:
                        cursor.execute('''
                            INSERT INTO ai_knowledge_brain_sync
                                (brain_region, knowledge_type, sync_count, last_sync,
                                 contributors, created_at)
                            VALUES (?, ?, 1, ?, ?, ?)
                        ''', (brain_region, knowledge_type, now,
                              json.dumps(contrib_list, ensure_ascii=False), now))
                        conn.commit()
                        sync_count = 1
                        contributors_out = contrib_list
            logger.info('知识脑库同步: %s/%s（累计 %d 次）', brain_region, knowledge_type, sync_count)
            return {
                'success': True,
                'brain_region': brain_region,
                'knowledge_type': knowledge_type,
                'sync_count': sync_count,
                'last_sync': now,
                'contributors': contributors_out,
                'message': '知识脑库同步成功',
            }
        except Exception as e:
            logger.error('知识脑库同步失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI 治理规则 ----------
    def add_governance_rule(self, rule_name: str, rule_type: str,
                            rule_content: str,
                            enforcement_level: str = 'medium') -> Dict[str, Any]:
        """添加 AI 治理规则"""
        try:
            if rule_type not in AI_RULE_TYPES:
                return {'success': False, 'error': f'非法规则类型，可选: {AI_RULE_TYPES}'}
            now = datetime.now().isoformat()
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO ai_governance_rules
                            (rule_name, rule_type, rule_content, enforcement_level, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (rule_name, rule_type, rule_content, enforcement_level, now))
                    conn.commit()
            logger.info('添加 AI 治理规则: %s (%s)', rule_name, rule_type)
            return {
                'success': True,
                'rule_name': rule_name,
                'rule_type': rule_type,
                'enforcement_level': enforcement_level,
                'message': 'AI 治理规则添加成功',
            }
        except Exception as e:
            logger.error('添加 AI 治理规则失败: %s', e)
            return {'success': False, 'error': str(e)}

    def audit_ai_decision(self, agent_id: str, decision_content: str) -> Dict[str, Any]:
        """AI 行为审计：依据治理规则评估决策合规性并记录审计日志"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT rule_name, rule_type, rule_content, enforcement_level
                        FROM ai_governance_rules
                        WHERE rule_type IN ('audit', 'ethics', 'boundary')
                    ''')
                    rules = cursor.fetchall()
            # 关键词命中检测（简单合规评估）
            keywords_map = {
                'ethics': ['歧视', '偏见', '有害', '违规', '隐私泄露'],
                'boundary': ['越权', '超范围', '未经授权'],
            }
            content_text = decision_content or ''
            violations = []
            for rule in rules:
                hit = False
                for kw in keywords_map.get(rule['rule_type'], []):
                    if kw in content_text:
                        hit = True
                        break
                if hit:
                    violations.append({
                        'rule_name': rule['rule_name'],
                        'rule_type': rule['rule_type'],
                        'enforcement_level': rule['enforcement_level'],
                    })
            compliant = len(violations) == 0
            # 记录审计日志（复用协作日志表）
            self.log_collaboration(
                from_agent=agent_id,
                to_agent='governance_auditor',
                task_type='audit',
                content=decision_content,
                result='compliant' if compliant else 'violation',
                score=1.0 if compliant else 0.0,
            )
            logger.info('AI 行为审计: agent=%s 合规=%s', agent_id, compliant)
            return {
                'success': True,
                'agent_id': agent_id,
                'compliant': compliant,
                'violations': violations,
                'checked_rules': len(rules),
                'decision_excerpt': content_text[:200],
                'message': '审计通过，未发现违规' if compliant else f'发现 {len(violations)} 项潜在违规',
            }
        except Exception as e:
            logger.error('AI 行为审计失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 融合汇总 ----------
    def get_integration_summary(self) -> Dict[str, Any]:
        """获取 AI 系统融合汇总"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # 角色统计
                cursor.execute('SELECT COUNT(*) AS c FROM ai_employee_roles')
                role_count = cursor.fetchone()['c']
                cursor.execute('SELECT level, COUNT(*) AS c FROM ai_employee_roles GROUP BY level')
                level_dist = {r['level']: r['c'] for r in cursor.fetchall()}
                # 团队统计
                cursor.execute("SELECT COUNT(*) AS c FROM ai_cluster_teams WHERE status = 'active'")
                active_teams = cursor.fetchone()['c']
                # 引擎统计
                cursor.execute('SELECT COUNT(*) AS c FROM ai_engine_registry WHERE is_active = 1')
                active_engines = cursor.fetchone()['c']
                # 协作统计
                cursor.execute('SELECT COUNT(*) AS c, AVG(collaboration_score) AS avg_score FROM ai_collaboration_log')
                collab_row = cursor.fetchone()
                collab_count = collab_row['c']
                avg_collab_score = round(collab_row['avg_score'] or 0.0, 2)
                # 知识脑库统计
                cursor.execute('SELECT COUNT(*) AS c, COALESCE(SUM(sync_count), 0) AS s FROM ai_knowledge_brain_sync')
                kb_row = cursor.fetchone()
                kb_regions = kb_row['c']
                kb_total_sync = kb_row['s']
                # 治理规则统计
                cursor.execute('SELECT COUNT(*) AS c FROM ai_governance_rules')
                rule_count = cursor.fetchone()['c']
            summary = {
                'success': True,
                'ai_roles': role_count,
                'level_distribution': level_dist,
                'active_teams': active_teams,
                'active_engines': active_engines,
                'collaboration_count': collab_count,
                'avg_collaboration_score': avg_collab_score,
                'knowledge_regions': kb_regions,
                'knowledge_total_sync': kb_total_sync,
                'governance_rules': rule_count,
                'cluster_strategies': list(AI_CLUSTER_STRATEGIES.keys()),
                'role_types': list(AI_ROLE_TYPES.keys()),
                'message': 'AI 系统融合汇总获取成功',
            }
            logger.info('AI 系统融合汇总: 角色=%d 团队=%d 引擎=%d', role_count, active_teams, active_engines)
            return summary
        except Exception as e:
            logger.error('获取融合汇总失败: %s', e)
            return {'success': False, 'error': str(e)}


# 模块级单例（与项目其他服务保持一致）
ai_system_integration_service = AISystemIntegrationService()
