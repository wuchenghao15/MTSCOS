#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 题库进化与扩充服务 (QuestionBankEvolutionService)
=====================================================
提供题库的自动化审题、AI出题、难度校准、知识点标注、生命周期管理、
质量评分、智能组卷、IRT能力评估、错题归因与题目安全等进化能力。

核心能力：
1. AI审题引擎   - 错题检测 / 重复检测 / 超纲检测 / 敏感内容过滤
2. AI自动出题   - 基于学科、知识点、难度目标的模板化生成
3. 难度动态校准 - 基于正确率 / 答题时长 / 区分度自动调整
4. 知识点标注   - 关键词匹配的自动标注
5. 生命周期管理 - created→reviewing→published→active→feedback→optimizing→retired
6. 质量评分     - 综合正确率、使用量、反馈、区分度的加权评分
7. 智能组卷     - 遗传算法思路的约束满足组卷
8. IRT评估      - 三参数逻辑斯蒂模型(3PL)简化版的学生能力估计
9. 题目推荐     - 基于能力的最近发展区推荐
10. 错题归因    - 知识缺口 / 粗心 / 概念误区 / 时间压力
11. 题目安全    - 水印 / 访问级别 / 防作弊(同卷不同序、选项随机化、等价题替换)
"""

import os
import json
import math
import uuid
import random
import sqlite3
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 解析数据库路径：优先使用 core/db_path.get_db_path('app.db')，失败回退到 PROJECT_ROOT/app.db
try:
    from core.db_path import get_db_path as _mtscos_get_db_path  # type: ignore
    DATABASE_PATH = _mtscos_get_db_path('app.db')
except Exception:  # pragma: no cover - 路径解析兜底
    _PROJECT_ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    DATABASE_PATH = os.path.join(_PROJECT_ROOT, 'app.db')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)


# ========== 题库进化常量 ==========

# 进化日志类型
EVOLUTION_TYPES = ('audit', 'generate', 'calibrate', 'tag', 'lifecycle')

# 题目生命周期阶段（按演进顺序）
LIFECYCLE_STAGES = (
    'created',      # 新建
    'reviewing',    # 审核中
    'published',    # 已发布
    'active',       # 启用中
    'feedback',     # 反馈收集
    'optimizing',   # 优化中
    'retired',      # 已退役
)

# 题目类型
QUESTION_TYPES = ('single_choice', 'multiple_choice', 'true_false', 'fill_blank')

# 学科知识点库（用于超纲检测与自动标注）
KNOWLEDGE_BASE: Dict[str, List[str]] = {
    '数学': ['代数', '几何', '函数', '方程', '概率', '统计', '三角函数',
             '微积分', '数列', '不等式', '向量', '导数', '复数',
             '立体几何', '解析几何', '集合', '排列组合'],
    '语文': ['文言文', '现代文', '诗歌', '散文', '小说', '作文',
             '阅读理解', '修辞手法', '词语', '句式', '标点', '文学常识'],
    '英语': ['语法', '词汇', '阅读', '听力', '写作', '翻译',
             '完形填空', '时态', '从句', '虚拟语气', '非谓语动词'],
    '物理': ['力学', '运动学', '动力学', '电磁学', '光学', '热学',
             '声学', '能量', '动量', '电场', '磁场', '电路', '原子物理'],
    '化学': ['无机化学', '有机化学', '化学反应', '元素周期表', '化学键',
             '酸碱盐', '氧化还原', '化学平衡', '电化学', '物质结构'],
    '生物': ['细胞', '遗传', '进化', '生态', '生理', '分子生物',
             '基因', '光合作用', '呼吸作用', '神经系统', '免疫系统'],
}

# 敏感词表（用于敏感内容过滤）
SENSITIVE_WORDS = [
    '暴力', '色情', '赌博', '毒品', '歧视', '恐怖', '邪教',
    '反动', '传销', '自杀', '枪支', '诈骗',
]


class QuestionBankEvolutionService:
    """题库进化与扩充服务：覆盖审题、出题、校准、标注、组卷、评估、安全全流程。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_PATH
        self._lock = threading.RLock()
        self.init_tables()

    # ---------- 基础设施 ----------

    def _get_connection(self) -> sqlite3.Connection:
        # 确保目录存在，避免首次运行报错
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def init_tables(self) -> Dict[str, Any]:
        """初始化题库进化相关的全部数据表。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    # 题库进化日志
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_evolution_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            evolution_type TEXT NOT NULL,
                            question_id TEXT,
                            action TEXT,
                            details TEXT,
                            ai_agent TEXT,
                            confidence REAL,
                            created_at TEXT
                        )
                    ''')
                    # 题目质量指标
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_quality_metrics (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            question_id TEXT UNIQUE NOT NULL,
                            difficulty_score REAL DEFAULT 0.5,
                            usage_count INTEGER DEFAULT 0,
                            correct_rate REAL DEFAULT 0.0,
                            positive_feedback INTEGER DEFAULT 0,
                            negative_feedback INTEGER DEFAULT 0,
                            quality_score REAL DEFAULT 0.0,
                            discrimination REAL DEFAULT 0.0,
                            avg_response_time REAL DEFAULT 0.0,
                            last_calibrated TEXT,
                            created_at TEXT
                        )
                    ''')
                    # 题目生命周期
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_lifecycle (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            question_id TEXT NOT NULL,
                            stage TEXT NOT NULL,
                            stage_changed_at TEXT,
                            changed_by TEXT,
                            notes TEXT
                        )
                    ''')
                    # AI出题配置
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_generation_config (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            subject TEXT,
                            knowledge_points TEXT,
                            difficulty_target REAL,
                            question_type TEXT,
                            generation_count INTEGER,
                            template_id TEXT,
                            status TEXT DEFAULT 'pending',
                            created_at TEXT
                        )
                    ''')
                    # 题目安全配置
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_security (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            question_id TEXT UNIQUE NOT NULL,
                            watermark_enabled INTEGER DEFAULT 0,
                            access_level TEXT DEFAULT 'public',
                            download_restricted INTEGER DEFAULT 1,
                            anti_cheat_enabled INTEGER DEFAULT 0,
                            created_at TEXT
                        )
                    ''')
                    # 题目内容存储（支撑生成/审题/组卷等流程的本地题库）
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_items (
                            question_id TEXT PRIMARY KEY,
                            subject TEXT,
                            question_type TEXT,
                            stem TEXT,
                            options TEXT,
                            answer TEXT,
                            analysis TEXT,
                            knowledge_points TEXT,
                            difficulty REAL DEFAULT 0.5,
                            score REAL DEFAULT 5.0,
                            source TEXT DEFAULT 'manual',
                            equivalent_group TEXT,
                            created_at TEXT
                        )
                    ''')
                    # 答题记录（支撑难度校准与IRT评估）
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS question_bank_answer_records (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            question_id TEXT NOT NULL,
                            student_id TEXT,
                            is_correct INTEGER DEFAULT 0,
                            response_time REAL DEFAULT 0.0,
                            chosen_option TEXT,
                            total_score REAL DEFAULT 0.0,
                            created_at TEXT
                        )
                    ''')
                    conn.commit()
                    logger.info('题库进化服务数据表初始化完成: %s', self.db_path)
                    return {'success': True}
        except Exception as e:
            logger.error('题库进化服务数据表初始化失败: %s', e)
            return {'success': False, 'error': str(e)}

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _log_evolution(self, evolution_type: str, question_id: str,
                       action: str, details: Any,
                       ai_agent: str = 'QuestionBankEvolutionAgent',
                       confidence: float = 1.0,
                       conn: Optional[sqlite3.Connection] = None) -> None:
        """记录一条进化日志（优先复用调用方连接，避免写锁冲突）。"""
        try:
            if conn is not None:
                # 复用外层连接，由调用方统一提交事务
                conn.execute(
                    '''INSERT INTO question_bank_evolution_log
                       (evolution_type, question_id, action, details, ai_agent, confidence, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (evolution_type, question_id, action,
                     json.dumps(details, ensure_ascii=False),
                     ai_agent, confidence, self._now())
                )
            else:
                with self._get_connection() as c:
                    c.execute(
                        '''INSERT INTO question_bank_evolution_log
                           (evolution_type, question_id, action, details, ai_agent, confidence, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (evolution_type, question_id, action,
                         json.dumps(details, ensure_ascii=False),
                         ai_agent, confidence, self._now())
                    )
                    c.commit()
        except Exception as e:
            logger.error('写入进化日志失败: %s', e)

    def _get_question(self, conn: sqlite3.Connection, question_id: str) -> Optional[sqlite3.Row]:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            'SELECT * FROM question_bank_items WHERE question_id = ?',
            (question_id,)
        )
        return cur.fetchone()

    def _ensure_metrics(self, conn: sqlite3.Connection, question_id: str) -> None:
        """确保题目存在质量指标记录。"""
        conn.execute(
            '''INSERT OR IGNORE INTO question_bank_quality_metrics
               (question_id, difficulty_score, created_at)
               VALUES (?, 0.5, ?)''',
            (question_id, self._now())
        )

    def _ensure_lifecycle(self, conn: sqlite3.Connection, question_id: str,
                          stage: str = 'created', changed_by: str = 'system',
                          notes: str = '') -> None:
        """确保题目存在生命周期记录。"""
        cur = conn.execute(
            'SELECT id FROM question_bank_lifecycle WHERE question_id = ?',
            (question_id,)
        )
        if cur.fetchone() is None:
            conn.execute(
                '''INSERT INTO question_bank_lifecycle
                   (question_id, stage, stage_changed_at, changed_by, notes)
                   VALUES (?, ?, ?, ?, ?)''',
                (question_id, stage, self._now(), changed_by, notes)
            )

    # ---------- AI审题引擎 ----------

    def ai_audit_question(self, question_id: str) -> Dict[str, Any]:
        """AI审题：检测错题、重复、超纲、敏感内容。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    qd = dict(q)
                    issues: List[Dict[str, Any]] = []
                    stem = qd.get('stem') or ''
                    answer = qd.get('answer') or ''
                    options_raw = qd.get('options') or '[]'
                    try:
                        options = json.loads(options_raw)
                    except Exception:
                        options = []
                    subject = qd.get('subject') or ''
                    kp_raw = qd.get('knowledge_points') or '[]'
                    try:
                        kps = json.loads(kp_raw)
                    except Exception:
                        kps = []
                    qtype = qd.get('question_type') or ''

                    # 1) 错题检测
                    if not stem.strip():
                        issues.append({'type': 'error_question', 'message': '题干为空'})
                    if not answer.strip():
                        issues.append({'type': 'error_question', 'message': '答案为空'})
                    if qtype in ('single_choice', 'multiple_choice') and options:
                        opt_keys = [o.get('key') for o in options if isinstance(o, dict)]
                        if len(opt_keys) != len(set(opt_keys)):
                            issues.append({'type': 'error_question', 'message': '存在重复选项键'})
                        ans_keys = [a.strip() for a in answer.split(',') if a.strip()]
                        for ak in ans_keys:
                            if ak not in opt_keys:
                                issues.append({'type': 'error_question',
                                               'message': f'答案 {ak} 不在选项中'})
                                break

                    # 2) 重复检测（基于题干字符的 Jaccard 相似度）
                    cur = conn.execute(
                        'SELECT question_id, stem FROM question_bank_items '
                        'WHERE question_id != ?', (question_id,)
                    )
                    stem_set = set(stem)
                    for row in cur.fetchall():
                        other_id, other_stem = row[0], row[1] or ''
                        other_set = set(other_stem)
                        if not stem_set or not other_set:
                            continue
                        inter = len(stem_set & other_set)
                        union = len(stem_set | other_set)
                        sim = inter / union if union else 0.0
                        if sim >= 0.8:
                            issues.append({'type': 'duplicate',
                                           'message': f'与题目 {other_id} 重复（相似度 {sim:.2f}）'})
                            break

                    # 3) 超纲检测（知识点不在该学科知识库内）
                    scope = KNOWLEDGE_BASE.get(subject, [])
                    if scope:
                        for kp in kps:
                            in_scope = any(kp in s or s in kp for s in scope)
                            if not in_scope:
                                issues.append({'type': 'out_of_scope',
                                               'message': f'知识点「{kp}」可能超出 {subject} 大纲'})

                    # 4) 敏感内容过滤
                    full_text = stem + ' ' + answer + ' ' + qd.get('analysis', '')
                    for sw in SENSITIVE_WORDS:
                        if sw in full_text:
                            issues.append({'type': 'sensitive',
                                           'message': f'检测到敏感词「{sw}」'})

                    confidence = round(1.0 - len(issues) * 0.2, 2)
                    if confidence < 0:
                        confidence = 0.0
                    passed = len(issues) == 0

                    # 审题不通过则进入审核阶段
                    if not passed:
                        self._set_lifecycle(conn, question_id, 'reviewing',
                                            'ai_audit', 'AI审题发现问题，转入审核')

                    self._log_evolution(
                        'audit', question_id, 'ai_audit',
                        {'passed': passed, 'issues': issues, 'confidence': confidence},
                        confidence=confidence, conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True,
                        'passed': passed,
                        'issues': issues,
                        'confidence': confidence,
                        'question_id': question_id,
                    }
        except Exception as e:
            logger.error('AI审题失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- AI自动出题 ----------

    def auto_generate_questions(self, subject: str, knowledge_points: List[str],
                                difficulty: float, count: int,
                                question_type: str = 'single_choice') -> Dict[str, Any]:
        """AI自动出题：基于学科/知识点/难度目标模板化生成题目。"""
        try:
            if question_type not in QUESTION_TYPES:
                return {'success': False, 'error': f'不支持的题型: {question_type}'}
            if not (0.0 <= difficulty <= 1.0):
                return {'success': False, 'error': 'difficulty 应在 0~1 之间'}
            if count <= 0:
                return {'success': False, 'error': 'count 必须大于 0'}
            kps = knowledge_points or KNOWLEDGE_BASE.get(subject, [])[:1]
            template_id = f'tpl_{uuid.uuid4().hex[:8]}'
            now = self._now()
            generated: List[Dict[str, Any]] = []

            with self._lock:
                with self._get_connection() as conn:
                    # 记录出题配置
                    conn.execute(
                        '''INSERT INTO question_bank_generation_config
                           (subject, knowledge_points, difficulty_target,
                            question_type, generation_count, template_id, status, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, 'running', ?)''',
                        (subject, json.dumps(kps, ensure_ascii=False),
                         difficulty, question_type, count, template_id, now)
                    )
                    for i in range(count):
                        kp = kps[i % len(kps)]
                        q = self._build_question(subject, kp, difficulty, question_type, i)
                        qid = f'q_{uuid.uuid4().hex[:12]}'
                        conn.execute(
                            '''INSERT INTO question_bank_items
                               (question_id, subject, question_type, stem, options, answer,
                                analysis, knowledge_points, difficulty, score, source,
                                equivalent_group, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ai_generated', ?, ?)''',
                            (qid, subject, question_type, q['stem'],
                             json.dumps(q['options'], ensure_ascii=False), q['answer'],
                             q['analysis'], json.dumps([kp], ensure_ascii=False),
                             difficulty, q['score'], q['equivalent_group'], now)
                        )
                        # 初始化质量指标与生命周期
                        self._ensure_metrics(conn, qid)
                        self._ensure_lifecycle(conn, qid, 'created', 'ai_generator',
                                               f'AI生成({template_id})')
                        # 安全默认配置
                        conn.execute(
                            '''INSERT OR IGNORE INTO question_bank_security
                               (question_id, watermark_enabled, access_level,
                                download_restricted, anti_cheat_enabled, created_at)
                               VALUES (?, 0, 'internal', 1, 0, ?)''',
                            (qid, now)
                        )
                        generated.append({
                            'question_id': qid, 'stem': q['stem'],
                            'options': q['options'], 'answer': q['answer'],
                            'knowledge_points': [kp], 'difficulty': difficulty,
                        })

                    # 更新配置状态
                    conn.execute(
                        'UPDATE question_bank_generation_config SET status = ? WHERE template_id = ?',
                        ('completed', template_id)
                    )
                    self._log_evolution(
                        'generate', None, 'auto_generate',
                        {'subject': subject, 'knowledge_points': kps,
                         'difficulty': difficulty, 'count': count,
                         'template_id': template_id, 'generated_ids': [g['question_id'] for g in generated]},
                        conn=conn
                    )
                    conn.commit()
                    logger.info('AI生成题目 %d 道 (学科=%s, 模板=%s)', count, subject, template_id)
                    return {
                        'success': True,
                        'template_id': template_id,
                        'generated': generated,
                        'count': len(generated),
                    }
        except Exception as e:
            logger.error('AI自动出题失败: %s', e)
            return {'success': False, 'error': str(e)}

    def _build_question(self, subject: str, kp: str, difficulty: float,
                        qtype: str, idx: int) -> Dict[str, Any]:
        """根据题型构建单道题目的内容（模板化生成）。"""
        diff_label = ['基础', '一般', '中等', '较难', '困难'][min(int(difficulty * 4.99), 4)]
        seed = hash(f'{subject}{kp}{idx}{difficulty}') & 0xFFFFFFFF
        rnd = random.Random(seed)

        if qtype == 'single_choice':
            stem = (f'【{subject}·{kp}·{diff_label}】第{idx + 1}题：'
                    f'关于「{kp}」，下列说法正确的是？')
            correct = rnd.choice(['A', 'B', 'C', 'D'])
            options = [
                {'key': 'A', 'text': f'{kp}的基本定义表述正确'},
                {'key': 'B', 'text': f'{kp}与无关概念混淆（干扰项）'},
                {'key': 'C', 'text': f'{kp}的应用场景错误描述'},
                {'key': 'D', 'text': f'{kp}的性质被反向表述'},
            ]
            # 把正确描述放到正确键
            for opt in options:
                opt['text'] = (opt['text'] + '（正确）') if opt['key'] == correct else opt['text']
            answer = correct
            analysis = f'本题考查{kp}，正确选项为{correct}，难度等级{diff_label}。'
            score = 5.0
        elif qtype == 'multiple_choice':
            stem = (f'【{subject}·{kp}·{diff_label}】第{idx + 1}题：'
                    f'关于「{kp}」，下列说法正确的有（多选）？')
            options = [
                {'key': 'A', 'text': f'{kp}性质一（正确）'},
                {'key': 'B', 'text': f'{kp}性质二（正确）'},
                {'key': 'C', 'text': f'{kp}性质三（错误）'},
                {'key': 'D', 'text': f'{kp}性质四（错误）'},
            ]
            answer = 'A,B'
            analysis = f'本题考查{kp}的多项性质，正确选项为A、B。'
            score = 6.0
        elif qtype == 'true_false':
            truth = rnd.choice([True, False])
            stem = (f'【{subject}·{kp}·{diff_label}】第{idx + 1}题：'
                    f'判断题：「{kp}的相关表述符合上述描述。」')
            options = [{'key': '对', 'text': '正确'}, {'key': '错', 'text': '错误'}]
            answer = '对' if truth else '错'
            analysis = f'本题考查{kp}，判断结果为{answer}。'
            score = 3.0
        else:  # fill_blank
            stem = (f'【{subject}·{kp}·{diff_label}】第{idx + 1}题：'
                    f'填空题：{kp}的核心概念是指________。')
            options = []
            answer = kp
            analysis = f'本题考查{kp}的定义填空。'
            score = 4.0

        # 等价题分组：同知识点同题型视为可替换等价题
        equivalent_group = f'eq_{subject}_{kp}_{qtype}'
        return {
            'stem': stem, 'options': options, 'answer': answer,
            'analysis': analysis, 'score': score,
            'equivalent_group': equivalent_group,
        }

    # ---------- 难度校准 ----------

    def calibrate_difficulty(self, question_id: str) -> Dict[str, Any]:
        """基于答题数据（正确率/答题时长/区分度）校准题目难度。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    self._ensure_metrics(conn, question_id)

                    cur = conn.execute(
                        'SELECT is_correct, response_time, total_score '
                        'FROM question_bank_answer_records WHERE question_id = ?',
                        (question_id,)
                    )
                    rows = cur.fetchall()
                    if not rows:
                        # 无答题数据，保持原难度并记录
                        self._log_evolution('calibrate', question_id, 'calibrate_no_data',
                                            {'reason': '暂无答题数据，难度维持'}, conn=conn)
                        conn.commit()
                        return {'success': True, 'question_id': question_id,
                                'difficulty_score': q['difficulty'],
                                'message': '暂无答题数据，难度维持'}

                    n = len(rows)
                    correct = sum(1 for r in rows if r[0])
                    correct_rate = correct / n
                    avg_time = sum(r[1] for r in rows) / n if n else 0.0

                    # 区分度：高分组(总分前27%)正确率 - 低分组(后27%)正确率
                    sorted_rows = sorted(rows, key=lambda r: r[2] or 0.0, reverse=True)
                    k = max(1, int(n * 0.27))
                    high = sorted_rows[:k]
                    low = sorted_rows[-k:]
                    high_rate = sum(1 for r in high if r[0]) / len(high) if high else 0.0
                    low_rate = sum(1 for r in low if r[0]) / len(low) if low else 0.0
                    discrimination = high_rate - low_rate

                    # 难度校准：正确率越高 -> 难度越低；答题时长偏长 -> 略增难度
                    # base = 1 - correct_rate（经典难度指数）
                    base_diff = 1.0 - correct_rate
                    # 时长修正：超过平均基准 60s 视为偏难
                    time_factor = max(-0.1, min(0.1, (avg_time - 60.0) / 600.0))
                    # 区分度过低时向 0.5 收敛（区分度好的题难度多在0.3-0.7）
                    if discrimination < 0.1:
                        base_diff = 0.5 * 0.3 + base_diff * 0.7
                    new_diff = max(0.0, min(1.0, base_diff + time_factor))

                    conn.execute(
                        '''UPDATE question_bank_quality_metrics
                           SET difficulty_score = ?, correct_rate = ?,
                               discrimination = ?, avg_response_time = ?,
                               usage_count = ?, last_calibrated = ?
                           WHERE question_id = ?''',
                        (round(new_diff, 4), round(correct_rate, 4),
                         round(discrimination, 4), round(avg_time, 2),
                         n, self._now(), question_id)
                    )
                    self._log_evolution(
                        'calibrate', question_id, 'calibrate_difficulty',
                        {
                            'sample_size': n, 'correct_rate': round(correct_rate, 4),
                            'avg_response_time': round(avg_time, 2),
                            'discrimination': round(discrimination, 4),
                            'old_difficulty': q['difficulty'],
                            'new_difficulty': round(new_diff, 4),
                        },
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True, 'question_id': question_id,
                        'old_difficulty': q['difficulty'],
                        'new_difficulty': round(new_diff, 4),
                        'correct_rate': round(correct_rate, 4),
                        'discrimination': round(discrimination, 4),
                        'avg_response_time': round(avg_time, 2),
                        'sample_size': n,
                    }
        except Exception as e:
            logger.error('难度校准失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 知识点自动标注 ----------

    def auto_tag_knowledge_points(self, question_id: str) -> Dict[str, Any]:
        """自动知识点标注：基于学科知识库的关键词匹配。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    qd = dict(q)
                    subject = qd.get('subject') or ''
                    scope = KNOWLEDGE_BASE.get(subject, [])
                    text = (qd.get('stem') or '') + ' ' + (qd.get('analysis') or '')

                    tagged: List[str] = []
                    # 优先匹配学科内知识点
                    for kp in scope:
                        if kp in text:
                            tagged.append(kp)
                    # 跨学科兜底匹配
                    if not tagged:
                        for subj_kps in KNOWLEDGE_BASE.values():
                            for kp in subj_kps:
                                if kp in text and kp not in tagged:
                                    tagged.append(kp)

                    # 兜底：若文本无任何命中，沿用学科首个知识点
                    if not tagged and scope:
                        tagged = [scope[0]]

                    conn.execute(
                        'UPDATE question_bank_items SET knowledge_points = ? WHERE question_id = ?',
                        (json.dumps(tagged, ensure_ascii=False), question_id)
                    )
                    self._log_evolution(
                        'tag', question_id, 'auto_tag',
                        {'subject': subject, 'tagged': tagged,
                         'previous': qd.get('knowledge_points')},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True, 'question_id': question_id,
                        'knowledge_points': tagged,
                    }
        except Exception as e:
            logger.error('自动知识点标注失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 生命周期管理 ----------

    def _set_lifecycle(self, conn: sqlite3.Connection, question_id: str,
                       new_stage: str, changed_by: str = 'system',
                       notes: str = '') -> None:
        """内部方法：写入生命周期记录。"""
        conn.execute(
            '''INSERT INTO question_bank_lifecycle
               (question_id, stage, stage_changed_at, changed_by, notes)
               VALUES (?, ?, ?, ?, ?)''',
            (question_id, new_stage, self._now(), changed_by, notes)
        )

    def manage_lifecycle(self, question_id: str, new_stage: str,
                         notes: str = '', changed_by: str = 'operator') -> Dict[str, Any]:
        """管理题目生命周期：校验阶段合法性并写入流转记录。"""
        try:
            if new_stage not in LIFECYCLE_STAGES:
                return {'success': False,
                        'error': f'非法生命周期阶段: {new_stage}，可选: {list(LIFECYCLE_STAGES)}'}
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}

                    # 查询当前阶段
                    cur = conn.execute(
                        'SELECT stage FROM question_bank_lifecycle WHERE question_id = ? '
                        'ORDER BY id DESC LIMIT 1', (question_id,)
                    )
                    row = cur.fetchone()
                    old_stage = row[0] if row else 'created'

                    self._set_lifecycle(conn, question_id, new_stage, changed_by, notes)
                    # 退役时同步安全访问级别
                    if new_stage == 'retired':
                        conn.execute(
                            "UPDATE question_bank_security SET access_level = 'archived' "
                            'WHERE question_id = ?', (question_id,)
                        )
                    self._log_evolution(
                        'lifecycle', question_id, 'manage_lifecycle',
                        {'old_stage': old_stage, 'new_stage': new_stage,
                         'changed_by': changed_by, 'notes': notes},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True, 'question_id': question_id,
                        'old_stage': old_stage, 'new_stage': new_stage,
                    }
        except Exception as e:
            logger.error('生命周期管理失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 质量评分 ----------

    def calculate_quality_score(self, question_id: str) -> Dict[str, Any]:
        """计算题目质量评分：综合正确率合理性、使用量、反馈、区分度。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    self._ensure_metrics(conn, question_id)
                    cur = conn.execute(
                        'SELECT difficulty_score, usage_count, correct_rate, '
                        'positive_feedback, negative_feedback, quality_score, '
                        'discrimination FROM question_bank_quality_metrics '
                        'WHERE question_id = ?', (question_id,)
                    )
                    row = cur.fetchone()
                    if not row:
                        return {'success': False, 'error': '质量指标缺失'}
                    diff, usage, rate, pos, neg, _old_q, disc = row

                    # 1) 正确率合理性：越接近目标难度对应的正确率越好
                    target_rate = 1.0 - (diff or 0.5)
                    rate_score = 1.0 - min(1.0, abs((rate or 0.0) - target_rate))
                    # 2) 使用量得分：使用越多越可靠（对数压缩）
                    usage_score = min(1.0, math.log1p(usage or 0) / math.log1p(50))
                    # 3) 反馈得分
                    total_fb = (pos or 0) + (neg or 0)
                    fb_score = ((pos or 0) / total_fb) if total_fb > 0 else 0.5
                    # 4) 区分度得分：区分度越高越好（>=0.3 优秀）
                    disc_score = max(0.0, min(1.0, (disc or 0.0) / 0.4))

                    quality = (rate_score * 0.35 + usage_score * 0.15 +
                               fb_score * 0.20 + disc_score * 0.30)
                    quality = round(quality, 4)

                    conn.execute(
                        'UPDATE question_bank_quality_metrics SET quality_score = ? '
                        'WHERE question_id = ?', (quality, question_id)
                    )
                    self._log_evolution(
                        'calibrate', question_id, 'calculate_quality',
                        {'quality_score': quality, 'rate_score': round(rate_score, 4),
                         'usage_score': round(usage_score, 4),
                         'fb_score': round(fb_score, 4),
                         'disc_score': round(disc_score, 4)},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True, 'question_id': question_id,
                        'quality_score': quality,
                        'components': {
                            'rate_score': round(rate_score, 4),
                            'usage_score': round(usage_score, 4),
                            'fb_score': round(fb_score, 4),
                            'disc_score': round(disc_score, 4),
                        },
                    }
        except Exception as e:
            logger.error('质量评分失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 智能组卷（遗传算法思路） ----------

    def smart_assemble_paper(self, constraints: Dict[str, Any]) -> Dict[str, Any]:
        """智能组卷：基于遗传算法在约束（总分/题量/难度/知识点覆盖）下求解。"""
        try:
            total_score = float(constraints.get('total_score', 100))
            question_count = int(constraints.get('question_count', 20))
            target_diff = float(constraints.get('target_difficulty', 0.5))
            kp_required = constraints.get('knowledge_coverage', []) or []
            subject = constraints.get('subject')
            qtype = constraints.get('question_type')
            seed = constraints.get('seed', 42)
            pop_size = int(constraints.get('population_size', 30))
            generations = int(constraints.get('generations', 60))

            if question_count <= 0:
                return {'success': False, 'error': '题量必须大于 0'}

            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    # 候选题池：仅取已发布/启用中的题目
                    query = ('SELECT qi.* FROM question_bank_items qi '
                             "WHERE qi.question_id IN ("
                             " SELECT q2.question_id FROM question_bank_lifecycle q2 "
                             " WHERE q2.stage IN ('published','active') "
                             " GROUP BY q2.question_id HAVING MAX(q2.id))")
                    params: List[Any] = []
                    if subject:
                        query += ' AND qi.subject = ?'
                        params.append(subject)
                    if qtype:
                        query += ' AND qi.question_type = ?'
                        params.append(qtype)
                    cur = conn.execute(query, params)
                    pool = [dict(r) for r in cur.fetchall()]

                    if len(pool) < question_count:
                        return {'success': False,
                                'error': f'候选题量不足(需{question_count}，实{len(pool)})'}

                    # 解析候选题的知识点
                    for p in pool:
                        try:
                            p['_kp'] = json.loads(p.get('knowledge_points') or '[]')
                        except Exception:
                            p['_kp'] = []

                    rnd = random.Random(seed)

                    def fitness(chrom: List[Dict[str, Any]]) -> float:
                        score_sum = sum(float(c.get('score') or 0) for c in chrom)
                        diff_avg = (sum(float(c.get('difficulty') or 0.5) for c in chrom)
                                    / len(chrom))
                        covered = set()
                        for c in chrom:
                            covered.update(c['_kp'])
                        missing = len(set(kp_required) - covered)
                        # 适应度：越高越好（惩罚偏离）
                        score_pen = abs(score_sum - total_score) * 1.0
                        diff_pen = abs(diff_avg - target_diff) * 100.0
                        miss_pen = missing * 30.0
                        # 重复题惩罚
                        dup_pen = (len(chrom) - len(set(c['question_id'] for c in chrom))) * 50.0
                        return -(score_pen + diff_pen + miss_pen + dup_pen)

                    # 初始化种群
                    population = []
                    for _ in range(pop_size):
                        chrom = rnd.sample(pool, question_count)
                        population.append(chrom)

                    best = max(population, key=fitness)
                    best_fit = fitness(best)

                    for _gen in range(generations):
                        # 锦标赛选择
                        def tournament():
                            a, b = rnd.choice(population), rnd.choice(population)
                            return a if fitness(a) >= fitness(b) else b

                        new_pop = [best]
                        while len(new_pop) < pop_size:
                            p1, p2 = tournament(), tournament()
                            # 单点交叉
                            point = rnd.randint(1, question_count - 1)
                            child = p1[:point] + p2[point:]
                            # 去重补全：替换重复题
                            seen = set()
                            for i, c in enumerate(child):
                                if c['question_id'] in seen:
                                    child[i] = rnd.choice(pool)
                                else:
                                    seen.add(c['question_id'])
                            # 变异
                            if rnd.random() < 0.2:
                                mi = rnd.randint(0, question_count - 1)
                                child[mi] = rnd.choice(pool)
                            new_pop.append(child)
                        population = new_pop
                        cur_best = max(population, key=fitness)
                        if fitness(cur_best) > best_fit:
                            best, best_fit = cur_best, fitness(cur_best)

                    score_sum = sum(float(c.get('score') or 0) for c in best)
                    diff_avg = (sum(float(c.get('difficulty') or 0.5) for c in best)
                                / len(best))
                    covered = set()
                    for c in best:
                        covered.update(c['_kp'])

                    paper_questions = [{
                        'question_id': c['question_id'],
                        'stem': c.get('stem'),
                        'question_type': c.get('question_type'),
                        'score': c.get('score'),
                        'difficulty': c.get('difficulty'),
                        'knowledge_points': c['_kp'],
                    } for c in best]

                    paper_id = f'paper_{uuid.uuid4().hex[:10]}'
                    self._log_evolution(
                        'generate', None, 'smart_assemble_paper',
                        {'paper_id': paper_id, 'constraints': constraints,
                         'total_score': score_sum, 'avg_difficulty': round(diff_avg, 4),
                         'knowledge_covered': sorted(covered),
                         'fitness': round(best_fit, 4),
                         'question_ids': [c['question_id'] for c in best]},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True,
                        'paper_id': paper_id,
                        'questions': paper_questions,
                        'actual_total_score': round(score_sum, 2),
                        'actual_avg_difficulty': round(diff_avg, 4),
                        'knowledge_covered': sorted(covered),
                        'missing_knowledge': sorted(set(kp_required) - covered),
                        'fitness': round(best_fit, 4),
                    }
        except Exception as e:
            logger.error('智能组卷失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 进化汇总 ----------

    def get_evolution_summary(self) -> Dict[str, Any]:
        """获取题库进化汇总：各类型日志数、生命周期分布、平均质量等。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    # 进化日志按类型统计
                    cur.execute(
                        'SELECT evolution_type, COUNT(*) AS cnt '
                        'FROM question_bank_evolution_log GROUP BY evolution_type'
                    )
                    by_type = {r['evolution_type']: r['cnt'] for r in cur.fetchall()}

                    # 生命周期分布（取每题最新阶段）
                    cur.execute(
                        'SELECT stage, COUNT(*) AS cnt FROM ('
                        ' SELECT question_id, stage FROM question_bank_lifecycle '
                        ' WHERE id IN (SELECT MAX(id) FROM question_bank_lifecycle '
                        '              GROUP BY question_id)) '
                        'GROUP BY stage'
                    )
                    stage_dist = {r['stage']: r['cnt'] for r in cur.fetchall()}

                    # 题目总量与平均质量
                    cur.execute('SELECT COUNT(*) AS c FROM question_bank_items')
                    total_q = cur.fetchone()['c']
                    cur.execute(
                        'SELECT AVG(quality_score) AS q, AVG(difficulty_score) AS d, '
                        'AVG(correct_rate) AS r, SUM(usage_count) AS u '
                        'FROM question_bank_quality_metrics'
                    )
                    agg = cur.fetchone()
                    cur.execute(
                        'SELECT action, COUNT(*) AS cnt, '
                        "MAX(created_at) AS last_at "
                        'FROM question_bank_evolution_log GROUP BY action '
                        'ORDER BY cnt DESC LIMIT 10'
                    )
                    recent_actions = [dict(r) for r in cur.fetchall()]

                    summary = {
                        'total_questions': total_q,
                        'evolution_by_type': by_type,
                        'lifecycle_distribution': stage_dist,
                        'avg_quality_score': round(agg['q'] or 0.0, 4) if agg['q'] else 0.0,
                        'avg_difficulty': round(agg['d'] or 0.0, 4) if agg['d'] else 0.0,
                        'avg_correct_rate': round(agg['r'] or 0.0, 4) if agg['r'] else 0.0,
                        'total_usage': agg['u'] or 0,
                        'recent_actions': recent_actions,
                    }
                    return {'success': True, 'summary': summary}
        except Exception as e:
            logger.error('获取进化汇总失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- IRT 项目反应理论评估（3PL 简化版） ----------

    @staticmethod
    def _irt_probability(theta: float, a: float, b: float, c: float) -> float:
        """三参数逻辑斯蒂模型(3PL)简化版：P(θ)=c+(1-c)/(1+exp(-a(θ-b)))。"""
        try:
            z = -a * (theta - b)
            p = c + (1.0 - c) / (1.0 + math.exp(z))
        except OverflowError:
            p = 1.0 if z < 0 else c
        return max(0.0, min(1.0, p))

    def _get_irt_params(self, conn: sqlite3.Connection, question_id: str,
                        qtype: str) -> Tuple[float, float, float]:
        """获取题目的IRT参数 (a=区分度, b=难度, c=猜测参数)。"""
        cur = conn.execute(
            'SELECT difficulty_score, discrimination FROM question_bank_quality_metrics '
            'WHERE question_id = ?', (question_id,)
        )
        row = cur.fetchone()
        if row:
            diff = row[0] if row[0] is not None else 0.5
            disc = row[1] if row[1] is not None else 1.0
        else:
            diff, disc = 0.5, 1.0
        # 难度 b：将 0~1 映射到 -3~3
        b = (diff - 0.5) * 6.0
        # 区分度 a：默认1.0，区分度指标放大到合理范围
        a = max(0.2, min(2.5, disc * 2.0 + 0.5))
        # 猜测参数 c：选择题按选项数估算，其他为0
        if qtype == 'single_choice':
            c = 0.25
        elif qtype == 'true_false':
            c = 0.5
        elif qtype == 'multiple_choice':
            c = 0.1
        else:
            c = 0.0
        return a, b, c

    def apply_irt_assessment(self, student_answers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """IRT项目反应理论评估学生能力：基于3PL模型的最大似然估计。"""
        try:
            if not student_answers:
                return {'success': False, 'error': '答题数据为空'}
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    # 收集每题的IRT参数与作答
                    items: List[Dict[str, Any]] = []
                    for sa in student_answers:
                        qid = sa.get('question_id')
                        is_correct = int(sa.get('is_correct', 0))
                        q = self._get_question(conn, qid) if qid else None
                        if not q:
                            continue
                        a, b, c = self._get_irt_params(conn, qid, q['question_type'])
                        items.append({
                            'question_id': qid, 'u': is_correct,
                            'a': a, 'b': b, 'c': c,
                            'knowledge_points': json.loads(q['knowledge_points'] or '[]'),
                        })
                    if not items:
                        return {'success': False, 'error': '未找到有效答题题目'}

                    def log_likelihood(theta: float) -> float:
                        total = 0.0
                        for it in items:
                            p = self._irt_probability(theta, it['a'], it['b'], it['c'])
                            p = max(1e-6, min(1 - 1e-6, p))
                            if it['u']:
                                total += math.log(p)
                            else:
                                total += math.log(1.0 - p)
                        return total

                    # 网格搜索 + 逐步精化
                    best_theta, best_ll = 0.0, log_likelihood(0.0)
                    step = 0.5
                    start, end = -3.0, 3.0
                    for _ in range(6):
                        theta = start
                        while theta <= end:
                            ll = log_likelihood(theta)
                            if ll > best_ll:
                                best_ll, best_theta = ll, theta
                            theta += step
                        # 在最优点附近精化
                        start = best_theta - step
                        end = best_theta + step
                        step /= 5.0

                    # 全对或全错时边界处理
                    all_correct = all(it['u'] for it in items)
                    all_wrong = all(not it['u'] for it in items)
                    if all_correct:
                        best_theta = max(best_theta, 2.5)
                    if all_wrong:
                        best_theta = min(best_theta, -2.5)

                    # 能力等级
                    if best_theta >= 1.5:
                        level, desc = 'excellent', '优秀'
                    elif best_theta >= 0.5:
                        level, desc = 'good', '良好'
                    elif best_theta >= -0.5:
                        level, desc = 'average', '中等'
                    elif best_theta >= -1.5:
                        level, desc = 'below_average', '偏弱'
                    else:
                        level, desc = 'weak', '薄弱'

                    # 知识点掌握情况
                    kp_stat: Dict[str, Dict[str, int]] = {}
                    for it in items:
                        for kp in it['knowledge_points']:
                            if kp not in kp_stat:
                                kp_stat[kp] = {'correct': 0, 'total': 0}
                            kp_stat[kp]['total'] += 1
                            if it['u']:
                                kp_stat[kp]['correct'] += 1
                    kp_mastery = {
                        kp: round(v['correct'] / v['total'], 4) if v['total'] else 0.0
                        for kp, v in kp_stat.items()
                    }

                    self._log_evolution(
                        'calibrate', None, 'irt_assessment',
                        {'ability': round(best_theta, 4), 'level': level,
                         'item_count': len(items), 'kp_mastery': kp_mastery},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True,
                        'ability_theta': round(best_theta, 4),
                        'level': level,
                        'level_description': desc,
                        'log_likelihood': round(best_ll, 4),
                        'item_count': len(items),
                        'knowledge_mastery': kp_mastery,
                    }
        except Exception as e:
            logger.error('IRT评估失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 题目推荐 ----------

    def recommend_questions(self, student_ability: float,
                            count: int = 10) -> Dict[str, Any]:
        """基于学生能力推荐题目：选择最近发展区(答对概率0.4~0.7)的题目。"""
        try:
            if count <= 0:
                return {'success': False, 'error': 'count 必须大于 0'}
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute(
                        'SELECT qi.question_id, qi.question_type, qi.stem, '
                        'qi.difficulty, qi.knowledge_points, qi.score '
                        'FROM question_bank_items qi WHERE qi.question_id IN ('
                        " SELECT q2.question_id FROM question_bank_lifecycle q2 "
                        " WHERE q2.stage IN ('published','active') "
                        ' GROUP BY q2.question_id HAVING MAX(q2.id))'
                    )
                    candidates = [dict(r) for r in cur.fetchall()]
                    if not candidates:
                        return {'success': False, 'error': '无可推荐题目'}

                    scored: List[Dict[str, Any]] = []
                    for c in candidates:
                        a, b, cc = self._get_irt_params(
                            conn, c['question_id'], c['question_type']
                        )
                        p = self._irt_probability(student_ability, a, b, cc)
                        # 最近发展区：目标概率 0.55，越接近越优先
                        target = 0.55
                        in_zpd = 0.4 <= p <= 0.7
                        score = abs(p - target)
                        scored.append({
                            'question_id': c['question_id'],
                            'stem': c['stem'],
                            'difficulty': c['difficulty'],
                            'score': c['score'],
                            'prob_correct': round(p, 4),
                            'in_zpd': in_zpd,
                            'priority_score': round(score, 4),
                            'knowledge_points': json.loads(c['knowledge_points'] or '[]'),
                        })
                    # 优先 ZPD 内题目，再按接近度排序
                    scored.sort(key=lambda x: (not x['in_zpd'], x['priority_score']))
                    recommended = scored[:count]
                    return {
                        'success': True,
                        'student_ability': student_ability,
                        'recommended': recommended,
                        'count': len(recommended),
                    }
        except Exception as e:
            logger.error('题目推荐失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 错题归因分析 ----------

    def analyze_error_attribution(self, wrong_answers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """错题归因分析：知识缺口/粗心/概念误区/时间压力。"""
        try:
            if not wrong_answers:
                return {'success': False, 'error': '错题数据为空'}
            attributions: List[Dict[str, Any]] = []
            agg = {'knowledge_gap': 0, 'careless': 0,
                   'misconception': 0, 'time_pressure': 0}
            kp_errors: Dict[str, int] = {}

            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    for wa in wrong_answers:
                        qid = wa.get('question_id')
                        resp_time = float(wa.get('response_time', 0.0))
                        chosen = wa.get('chosen_answer', '')
                        q = self._get_question(conn, qid) if qid else None
                        if not q:
                            continue
                        qd = dict(q)
                        kps = json.loads(qd.get('knowledge_points') or '[]')
                        reasons: List[str] = []

                        # 时间压力：答题时长过短（<15s）视为时间压力
                        if 0 < resp_time < 15.0:
                            reasons.append('time_pressure')
                        # 粗心：选项包含正确答案相邻键（A/B/C/D 相邻）或时长极短
                        correct_ans = qd.get('answer') or ''
                        if qd.get('question_type') == 'single_choice' and correct_ans and chosen:
                            adjacent = {'A': 'B', 'B': 'A', 'C': 'D', 'D': 'C'}
                            if adjacent.get(correct_ans) == chosen:
                                reasons.append('careless')
                        # 概念误区：选了干扰项（多个错误选项中典型误区）
                        if qd.get('question_type') in ('single_choice', 'multiple_choice'):
                            try:
                                opts = json.loads(qd.get('options') or '[]')
                                for opt in opts:
                                    if opt.get('key') == chosen and '错误' in (opt.get('text') or ''):
                                        reasons.append('misconception')
                                        break
                            except Exception:
                                pass
                        # 知识缺口：默认归因（若以上均未命中）
                        if not reasons:
                            reasons.append('knowledge_gap')

                        primary = reasons[0]
                        agg[primary] = agg.get(primary, 0) + 1
                        for kp in kps:
                            kp_errors[kp] = kp_errors.get(kp, 0) + 1

                        attributions.append({
                            'question_id': qid,
                            'knowledge_points': kps,
                            'response_time': resp_time,
                            'chosen_answer': chosen,
                            'correct_answer': correct_ans,
                            'attributions': reasons,
                            'primary': primary,
                        })

                    total = len(attributions) or 1
                    distribution = {k: round(v / total, 4) for k, v in agg.items()}
                    weak_kps = sorted(kp_errors.items(), key=lambda x: x[1], reverse=True)
                    # 推荐补救知识点（错误最多的前3个）
                    remediation = [kp for kp, _ in weak_kps[:3]]

                    self._log_evolution(
                        'calibrate', None, 'error_attribution',
                        {'total_errors': len(attributions),
                         'distribution': distribution,
                         'weak_knowledge': weak_kps[:5]},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True,
                        'total_errors': len(attributions),
                        'distribution': distribution,
                        'attributions': attributions,
                        'weak_knowledge_points': weak_kps,
                        'remediation_suggestion': remediation,
                    }
        except Exception as e:
            logger.error('错题归因分析失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 题目安全配置 ----------

    def setup_security(self, question_id: str, watermark: bool = True,
                       access_level: str = 'internal',
                       anti_cheat: bool = True) -> Dict[str, Any]:
        """题目安全配置：水印、访问级别、下载限制、防作弊。"""
        try:
            valid_levels = ('public', 'internal', 'confidential', 'archived')
            if access_level not in valid_levels:
                return {'success': False,
                        'error': f'非法访问级别，可选: {list(valid_levels)}'}
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    now = self._now()
                    # 下载受限：非公开级别默认限制下载
                    download_restricted = 1 if access_level != 'public' else 0
                    conn.execute(
                        '''INSERT INTO question_bank_security
                           (question_id, watermark_enabled, access_level,
                            download_restricted, anti_cheat_enabled, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(question_id) DO UPDATE SET
                            watermark_enabled = excluded.watermark_enabled,
                            access_level = excluded.access_level,
                            download_restricted = excluded.download_restricted,
                            anti_cheat_enabled = excluded.anti_cheat_enabled''',
                        (question_id, int(watermark), access_level,
                         download_restricted, int(anti_cheat), now)
                    )
                    self._log_evolution(
                        'lifecycle', question_id, 'setup_security',
                        {'watermark': watermark, 'access_level': access_level,
                         'download_restricted': bool(download_restricted),
                         'anti_cheat': anti_cheat},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True, 'question_id': question_id,
                        'watermark_enabled': watermark,
                        'access_level': access_level,
                        'download_restricted': bool(download_restricted),
                        'anti_cheat_enabled': anti_cheat,
                    }
        except Exception as e:
            logger.error('题目安全配置失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 防作弊：同卷不同序 / 选项随机化 / 等价题替换 ----------

    def generate_anti_cheat_variants(self, paper_question_ids: List[str],
                                     variant_count: int = 2,
                                     seed: Optional[int] = None) -> Dict[str, Any]:
        """生成防作弊试卷变体：同卷不同序、选项随机化、等价题替换。"""
        try:
            if not paper_question_ids:
                return {'success': False, 'error': '题目列表为空'}
            if variant_count <= 0:
                return {'success': False, 'error': '变体数量必须大于 0'}
            with self._lock:
                with self._get_connection() as conn:
                    conn.row_factory = sqlite3.Row
                    questions = []
                    for qid in paper_question_ids:
                        q = self._get_question(conn, qid)
                        if q:
                            questions.append(dict(q))
                    if not questions:
                        return {'success': False, 'error': '未找到有效题目'}

                    rnd = random.Random(seed)
                    variants: List[Dict[str, Any]] = []
                    for v in range(variant_count):
                        v_rnd = random.Random(rnd.random())
                        variant_questions: List[Dict[str, Any]] = []
                        for q in questions:
                            qd = dict(q)
                            # 等价题替换：尝试找同 equivalent_group 的其他题
                            eq_group = qd.get('equivalent_group')
                            if eq_group:
                                cur = conn.execute(
                                    'SELECT question_id, stem, options, answer FROM '
                                    'question_bank_items WHERE equivalent_group = ? '
                                    'AND question_id != ?',
                                    (eq_group, qd['question_id'])
                                )
                                eqs = cur.fetchall()
                                if eqs and v_rnd.random() < 0.3:
                                    eq = dict(v_rnd.choice(eqs))
                                    qd['question_id'] = eq['question_id']
                                    qd['stem'] = eq['stem']
                                    qd['options'] = eq['options']
                                    qd['answer'] = eq['answer']

                            # 选项随机化：对选择题打乱选项顺序并重映射答案
                            try:
                                options = json.loads(qd.get('options') or '[]')
                            except Exception:
                                options = []
                            answer_remap = qd.get('answer', '')
                            if options and qd.get('question_type') in (
                                    'single_choice', 'multiple_choice'):
                                orig_keys = [o.get('key') for o in options]
                                v_rnd.shuffle(options)
                                new_keys = orig_keys[:]  # 保持键名A/B/C/D
                                key_map = {}
                                for o, nk in zip(options, new_keys):
                                    old_key = o.get('key')
                                    o['key'] = nk
                                    key_map[old_key] = nk
                                # 重映射答案
                                remapped = []
                                for ak in [a.strip() for a in answer_remap.split(',') if a.strip()]:
                                    remapped.append(key_map.get(ak, ak))
                                answer_remap = ','.join(remapped)
                                qd['options'] = options
                                qd['answer'] = answer_remap

                            variant_questions.append({
                                'question_id': qd['question_id'],
                                'stem': qd.get('stem'),
                                'options': qd.get('options'),
                                'answer': qd.get('answer'),
                                'question_type': qd.get('question_type'),
                                'score': qd.get('score'),
                            })

                        # 同卷不同序：打乱题目顺序
                        v_rnd.shuffle(variant_questions)
                        variants.append({
                            'variant_index': v + 1,
                            'questions': variant_questions,
                            'question_order': [q['question_id'] for q in variant_questions],
                        })

                    self._log_evolution(
                        'lifecycle', None, 'anti_cheat_variants',
                        {'source_count': len(paper_question_ids),
                         'variant_count': variant_count,
                         'techniques': ['shuffle_order', 'randomize_options', 'equivalent_replace']},
                        conn=conn
                    )
                    conn.commit()
                    return {
                        'success': True,
                        'source_count': len(paper_question_ids),
                        'variant_count': len(variants),
                        'variants': variants,
                        'techniques': ['shuffle_order', 'randomize_options', 'equivalent_replace'],
                    }
        except Exception as e:
            logger.error('生成防作弊变体失败: %s', e)
            return {'success': False, 'error': str(e)}

    # ---------- 答题数据录入（支撑校准与IRT） ----------

    def record_answer(self, question_id: str, student_id: str,
                      is_correct: bool, response_time: float = 0.0,
                      chosen_option: str = '', total_score: float = 0.0) -> Dict[str, Any]:
        """记录答题数据，供难度校准与IRT评估使用。"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    q = self._get_question(conn, question_id)
                    if not q:
                        return {'success': False, 'error': '题目不存在'}
                    conn.execute(
                        '''INSERT INTO question_bank_answer_records
                           (question_id, student_id, is_correct, response_time,
                            chosen_option, total_score, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (question_id, student_id, int(is_correct),
                         response_time, chosen_option, total_score, self._now())
                    )
                    conn.commit()
                    return {'success': True, 'question_id': question_id,
                            'student_id': student_id, 'is_correct': is_correct}
        except Exception as e:
            logger.error('记录答题数据失败: %s', e)
            return {'success': False, 'error': str(e)}


if __name__ == '__main__':
    # 简单冒烟测试：生成题目 -> 审题 -> 标注 -> 录入答题 -> 校准 -> 质量评分 -> 组卷 -> IRT -> 归因
    svc = QuestionBankEvolutionService()
    print('init_tables:', svc.init_tables())
    gen = svc.auto_generate_questions('数学', ['代数', '函数'], 0.5, 5, 'single_choice')
    print('generate:', gen.get('count'), 'questions')
    if gen.get('generated'):
        qid = gen['generated'][0]['question_id']
        print('audit:', svc.ai_audit_question(qid))
        print('tag:', svc.auto_tag_knowledge_points(qid))
        svc.record_answer(qid, 's1', True, 40.0, 'A', 90.0)
        svc.record_answer(qid, 's2', False, 80.0, 'B', 50.0)
        svc.record_answer(qid, 's3', True, 35.0, 'A', 85.0)
        svc.record_answer(qid, 's4', False, 70.0, 'C', 40.0)
        print('calibrate:', svc.calibrate_difficulty(qid))
        print('quality:', svc.calculate_quality_score(qid))
        print('security:', svc.setup_security(qid, True, 'internal', True))
        # 发布全部题目以便组卷有足够候选
        for g in gen['generated']:
            svc.manage_lifecycle(g['question_id'], 'published', '审核通过')
        # IRT 评估
        irt_in = [{'question_id': g['question_id'], 'is_correct': i % 2 == 0}
                  for i, g in enumerate(gen['generated'])]
        print('irt:', svc.apply_irt_assessment(irt_in))
        # 推荐
        print('recommend:', svc.recommend_questions(0.5, 3).get('count'))
        # 错题归因
        wrong = [{'question_id': g['question_id'], 'is_correct': False,
                  'response_time': 12.0, 'chosen_answer': 'B'}
                 for g in gen['generated'][:2]]
        print('attribution:', svc.analyze_error_attribution(wrong).get('distribution'))
    # 组卷
    paper = svc.smart_assemble_paper({
        'total_score': 25, 'question_count': 5, 'target_difficulty': 0.5,
        'knowledge_coverage': ['代数', '函数'], 'subject': '数学',
    })
    print('paper:', paper.get('success'), 'score=', paper.get('actual_total_score'))
    if paper.get('questions'):
        print('anti_cheat:', svc.generate_anti_cheat_variants(
            [q['question_id'] for q in paper['questions']], 2).get('variant_count'))
    print('summary:', svc.get_evolution_summary().get('summary', {}).get('total_questions'))
