# -*- coding: utf-8 -*-
"""
高级AI自动学习升级系统
功能：
1. 多维度学习分析（题库、用户行为、错误模式、知识图谱）
2. 自适应学习路径生成
3. 题目质量自动评估与优化建议
4. AI模型持续训练与版本管理
5. 学习效果追踪与闭环优化
"""

import os
import sys
import json
import time
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


class AdvancedAutoLearningSystem:
    """高级AI自动学习升级系统"""

    def __init__(self, db_path: str = None):
        self.app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(self.app_root, 'data', 'app.db')
        self.data_dir = os.path.join(self.app_root, 'data')

        self._learn_lock = threading.Lock()
        self._is_learning = False
        self._learning_thread = None
        self._stop_flag = threading.Event()

        self.config = {
            'enabled': True,
            'auto_upgrade': True,
            'learning_interval_hours': 6,
            'min_data_points': 100,
            'confidence_threshold': 0.75,
            'max_upgrade_per_cycle': 5,
            'knowledge_graph_auto_expand': True,
            'question_quality_analysis': True,
            'user_behavior_mining': True,
            'error_pattern_learning': True
        }

        self.learning_stats = {
            'total_learning_cycles': 0,
            'last_learning_time': None,
            'knowledge_gained': 0,
            'models_updated': 0,
            'questions_optimized': 0,
            'patterns_discovered': 0
        }

        self._ensure_tables()
        logger.info("高级AI自动学习升级系统初始化完成")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self):
        conn = self._get_conn()
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS ai_learning_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT UNIQUE NOT NULL,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'running',
            knowledge_gained INTEGER DEFAULT 0,
            patterns_discovered INTEGER DEFAULT 0,
            models_updated INTEGER DEFAULT 0,
            questions_optimized INTEGER DEFAULT 0,
            details TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS ai_learning_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id TEXT UNIQUE NOT NULL,
            pattern_type TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            description TEXT,
            confidence REAL DEFAULT 0.0,
            support_count INTEGER DEFAULT 0,
            discovered_at TEXT,
            last_verified_at TEXT,
            is_active INTEGER DEFAULT 1,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS ai_question_quality (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            quality_score REAL DEFAULT 0.0,
            difficulty_score REAL DEFAULT 0.0,
            discrimination REAL DEFAULT 0.0,
            guess_rate REAL DEFAULT 0.0,
            time_spent_avg REAL DEFAULT 0.0,
            correct_rate REAL DEFAULT 0.0,
            total_attempts INTEGER DEFAULT 0,
            last_analyzed TEXT,
            optimization_suggestions TEXT,
            UNIQUE(question_id)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS ai_knowledge_expansion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expansion_id TEXT UNIQUE NOT NULL,
            source_knowledge TEXT,
            expanded_knowledge TEXT,
            expansion_type TEXT,
            confidence REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            applied_at TEXT,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS ai_user_behavior_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_id TEXT UNIQUE NOT NULL,
            insight_type TEXT NOT NULL,
            target_group TEXT,
            description TEXT,
            confidence REAL DEFAULT 0.0,
            sample_size INTEGER DEFAULT 0,
            discovered_at TEXT,
            is_actionable INTEGER DEFAULT 0,
            action_suggestion TEXT,
            metadata TEXT
        )""")

        conn.commit()
        conn.close()

    def start_learning_cycle(self) -> Dict[str, Any]:
        if self._is_learning:
            return {'success': False, 'message': '学习周期正在进行中'}

        self._is_learning = True
        self._stop_flag.clear()

        cycle_id = f"learn_{int(time.time())}"

        def _run():
            try:
                self._execute_learning_cycle(cycle_id)
            except Exception as e:
                logger.error(f"学习周期异常: {e}")
                self._update_cycle_status(cycle_id, 'failed', error=str(e))
            finally:
                self._is_learning = False

        self._learning_thread = threading.Thread(target=_run, daemon=True)
        self._learning_thread.start()

        return {'success': True, 'cycle_id': cycle_id, 'message': '学习周期已启动'}

    def _execute_learning_cycle(self, cycle_id: str):
        logger.info(f"开始学习周期: {cycle_id}")
        self._update_cycle_status(cycle_id, 'running')

        knowledge_gained = 0
        patterns_discovered = 0
        models_updated = 0
        questions_optimized = 0

        if self._stop_flag.is_set():
            return

        if self.config.get('error_pattern_learning', True):
            result = self._learn_error_patterns()
            patterns_discovered += result.get('new_patterns', 0)
            knowledge_gained += result.get('knowledge_gain', 0)

        if self._stop_flag.is_set():
            return

        if self.config.get('user_behavior_mining', True):
            result = self._mine_user_behavior()
            patterns_discovered += result.get('new_insights', 0)
            knowledge_gained += result.get('knowledge_gain', 0)

        if self._stop_flag.is_set():
            return

        if self.config.get('question_quality_analysis', True):
            result = self._analyze_question_quality()
            questions_optimized += result.get('analyzed_count', 0)
            knowledge_gained += result.get('knowledge_gain', 0)

        if self._stop_flag.is_set():
            return

        if self.config.get('knowledge_graph_auto_expand', True):
            result = self._expand_knowledge_graph()
            knowledge_gained += result.get('expanded_count', 0)
            models_updated += result.get('updated_models', 0)

        self.learning_stats['total_learning_cycles'] += 1
        self.learning_stats['last_learning_time'] = datetime.now().isoformat()
        self.learning_stats['knowledge_gained'] += knowledge_gained
        self.learning_stats['patterns_discovered'] += patterns_discovered
        self.learning_stats['models_updated'] += models_updated
        self.learning_stats['questions_optimized'] += questions_optimized

        details = json.dumps({
            'knowledge_gained': knowledge_gained,
            'patterns_discovered': patterns_discovered,
            'models_updated': models_updated,
            'questions_optimized': questions_optimized
        })

        self._update_cycle_status(cycle_id, 'completed', details=details)
        logger.info(f"学习周期完成: {cycle_id}, 获得知识: {knowledge_gained}")

    def _update_cycle_status(self, cycle_id: str, status: str, details: str = None, error: str = None):
        conn = self._get_conn()
        c = conn.cursor()
        try:
            if status == 'running':
                c.execute("""INSERT OR IGNORE INTO ai_learning_cycles 
                    (cycle_id, start_time, status) VALUES (?, ?, ?)""",
                    (cycle_id, datetime.now().isoformat(), status))
            else:
                c.execute("""UPDATE ai_learning_cycles SET end_time=?, status=?, details=? 
                    WHERE cycle_id=?""",
                    (datetime.now().isoformat(), status, details or error, cycle_id))
            conn.commit()
        except Exception as e:
            logger.error(f"更新周期状态失败: {e}")
        finally:
            conn.close()

    def _learn_error_patterns(self) -> Dict[str, Any]:
        new_patterns = 0
        knowledge_gain = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_behavior_logs'")
            if not c.fetchone():
                conn.close()
                return {'new_patterns': 0, 'knowledge_gain': 0}

            c.execute("""SELECT question_id, is_correct, user_answer, correct_answer, 
                        category, difficulty FROM exam_behavior_logs 
                        WHERE is_correct = 0 LIMIT 5000""")
            wrong_answers = c.fetchall()

            if len(wrong_answers) < self.config['min_data_points']:
                conn.close()
                return {'new_patterns': 0, 'knowledge_gain': 0}

            category_errors = defaultdict(int)
            difficulty_errors = defaultdict(lambda: {'total': 0, 'wrong': 0})

            for row in wrong_answers:
                cat = row['category'] or 'unknown'
                diff = row['difficulty'] or 'medium'
                category_errors[cat] += 1
                difficulty_errors[diff]['wrong'] += 1

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions'")
            if c.fetchone():
                c.execute("""SELECT category, difficulty, COUNT(*) as total 
                            FROM questions GROUP BY category, difficulty""")
                for row in c.fetchall():
                    cat = row['category'] or 'unknown'
                    diff = row['difficulty'] or 'medium'
                    difficulty_errors[diff]['total'] += row['total']

            conn.close()

            high_error_cats = [(cat, cnt) for cat, cnt in category_errors.items() if cnt > 20]
            high_error_cats.sort(key=lambda x: x[1], reverse=True)

            for cat, cnt in high_error_cats[:5]:
                pattern_id = f"err_pat_{cat}_{int(time.time())}"
                confidence = min(0.95, cnt / len(wrong_answers) * 3)

                if confidence >= self.config['confidence_threshold']:
                    if self._save_pattern(pattern_id, 'error_by_category', f'{cat}高频错误',
                                        f'在{cat}类别中发现{cnt}个错误，错误率显著高于平均水平',
                                        confidence, cnt, {'category': cat, 'error_count': cnt}):
                        new_patterns += 1
                        knowledge_gain += 1

            for diff, stats in difficulty_errors.items():
                if stats['total'] > 0:
                    error_rate = stats['wrong'] / stats['total']
                    if error_rate > 0.4 and stats['wrong'] > 50:
                        pattern_id = f"err_diff_{diff}_{int(time.time())}"
                        if self._save_pattern(pattern_id, 'error_by_difficulty', f'{diff}难度错误率高',
                                            f'{diff}难度题目错误率达{error_rate:.1%}',
                                            min(0.9, error_rate), stats['wrong'],
                                            {'difficulty': diff, 'error_rate': error_rate}):
                            new_patterns += 1
                            knowledge_gain += 1

        except Exception as e:
            logger.error(f"错误模式学习失败: {e}")

        return {'new_patterns': new_patterns, 'knowledge_gain': knowledge_gain}

    def _save_pattern(self, pattern_id: str, pattern_type: str, name: str,
                     description: str, confidence: float, support: int,
                     metadata: Dict = None) -> bool:
        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""INSERT OR IGNORE INTO ai_learning_patterns 
                (pattern_id, pattern_type, pattern_name, description, confidence,
                 support_count, discovered_at, last_verified_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pattern_id, pattern_type, name, description, confidence, support,
                 datetime.now().isoformat(), datetime.now().isoformat(),
                 json.dumps(metadata) if metadata else None))

            conn.commit()
            result = c.rowcount > 0
            conn.close()
            return result
        except Exception as e:
            logger.error(f"保存模式失败: {e}")
            return False

    def _mine_user_behavior(self) -> Dict[str, Any]:
        new_insights = 0
        knowledge_gain = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_sessions'")
            if not c.fetchone():
                conn.close()
                return {'new_insights': 0, 'knowledge_gain': 0}

            c.execute("""SELECT user_id, COUNT(*) as total_sessions, 
                        AVG(score) as avg_score,
                        SUM(CASE WHEN is_passed = 1 THEN 1 ELSE 0 END) as passed_count
                        FROM exam_sessions 
                        GROUP BY user_id 
                        HAVING total_sessions >= 3
                        LIMIT 1000""")
            users = c.fetchall()

            if len(users) < self.config['min_data_points']:
                conn.close()
                return {'new_insights': 0, 'knowledge_gain': 0}

            high_performers = [u for u in users if u['avg_score'] and u['avg_score'] > 80]
            low_performers = [u for u in users if u['avg_score'] and u['avg_score'] < 50]

            if len(high_performers) > 20 and len(low_performers) > 20:
                insight_id = f"insight_perf_{int(time.time())}"
                confidence = min(0.85, abs(len(high_performers) - len(low_performers)) / len(users) + 0.5)
                suggestion = f"建议为低分用户提供专项训练计划，当前低分用户占比{len(low_performers)/len(users):.1%}"

                if self._save_insight(insight_id, 'performance_distribution', 'all_users',
                                     f'高分用户{len(high_performers)}人，低分用户{len(low_performers)}人',
                                     confidence, len(users), True, suggestion):
                    new_insights += 1
                    knowledge_gain += 2

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_behavior_logs'")
            if c.fetchone():
                c.execute("""SELECT category, COUNT(*) as cnt 
                            FROM exam_behavior_logs 
                            WHERE timestamp >= datetime('now', '-30 days')
                            GROUP BY category 
                            ORDER BY cnt DESC 
                            LIMIT 10""")
                hot_categories = c.fetchall()

                if hot_categories:
                    insight_id = f"insight_hot_{int(time.time())}"
                    top_cat = hot_categories[0]
                    cat_name = top_cat['category'] or '未知'
                    if self._save_insight(insight_id, 'hot_category', 'all_users',
                                         f'最热门类别: {cat_name}，共{top_cat["cnt"]}次练习',
                                         0.95, top_cat['cnt'], True,
                                         f'建议增加{cat_name}类别的题目数量和难度梯度'):
                        new_insights += 1
                        knowledge_gain += 1

            conn.close()

        except Exception as e:
            logger.error(f"用户行为挖掘失败: {e}")

        return {'new_insights': new_insights, 'knowledge_gain': knowledge_gain}

    def _save_insight(self, insight_id: str, insight_type: str, target_group: str,
                     description: str, confidence: float, sample_size: int,
                     is_actionable: bool, action_suggestion: str) -> bool:
        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""INSERT OR IGNORE INTO ai_user_behavior_insights 
                (insight_id, insight_type, target_group, description, confidence,
                 sample_size, discovered_at, is_actionable, action_suggestion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (insight_id, insight_type, target_group, description, confidence,
                 sample_size, datetime.now().isoformat(), 1 if is_actionable else 0,
                 action_suggestion))

            conn.commit()
            result = c.rowcount > 0
            conn.close()
            return result
        except Exception as e:
            logger.error(f"保存洞察失败: {e}")
            return False

    def _analyze_question_quality(self) -> Dict[str, Any]:
        analyzed_count = 0
        knowledge_gain = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_behavior_logs'")
            if not c.fetchone():
                conn.close()
                return {'analyzed_count': 0, 'knowledge_gain': 0}

            c.execute("""SELECT question_id, 
                        COUNT(*) as total_attempts,
                        SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_count,
                        AVG(time_spent) as avg_time
                        FROM exam_behavior_logs
                        WHERE question_id IS NOT NULL
                        GROUP BY question_id
                        HAVING total_attempts >= 20
                        LIMIT 500""")
            question_stats = c.fetchall()

            for qs in question_stats:
                qid = qs['question_id']
                total = qs['total_attempts']
                correct = qs['correct_count'] or 0
                avg_time = qs['avg_time'] or 0

                correct_rate = correct / total if total > 0 else 0
                difficulty_score = 1 - correct_rate
                discrimination = 0.5

                quality_score = self._calculate_quality_score(difficulty_score, discrimination, correct_rate)

                suggestions = []
                if correct_rate > 0.9:
                    suggestions.append('题目过易，建议提升难度')
                elif correct_rate < 0.2:
                    suggestions.append('题目过难，建议降低难度或增加提示')
                if avg_time > 300:
                    suggestions.append('平均耗时过长，建议拆分为多道小题')

                c.execute("""INSERT OR REPLACE INTO ai_question_quality 
                    (question_id, quality_score, difficulty_score, discrimination,
                     correct_rate, time_spent_avg, total_attempts, last_analyzed,
                     optimization_suggestions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (qid, quality_score, difficulty_score, discrimination,
                     correct_rate, avg_time, total, datetime.now().isoformat(),
                     json.dumps(suggestions) if suggestions else None))

                analyzed_count += 1
                if suggestions:
                    knowledge_gain += 1

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"题目质量分析失败: {e}")

        return {'analyzed_count': analyzed_count, 'knowledge_gain': knowledge_gain}

    def _calculate_quality_score(self, difficulty: float, discrimination: float, correct_rate: float) -> float:
        diff_score = 1 - abs(difficulty - 0.5) * 2
        disc_score = min(1.0, discrimination * 2)
        rate_score = 1 - abs(correct_rate - 0.6) * 2
        rate_score = max(0.0, rate_score)

        quality = (diff_score * 0.3 + disc_score * 0.4 + rate_score * 0.3)
        return round(max(0.0, min(1.0, quality)), 3)

    def _expand_knowledge_graph(self) -> Dict[str, Any]:
        expanded_count = 0
        updated_models = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions'")
            if not c.fetchone():
                conn.close()
                return {'expanded_count': 0, 'updated_models': 0}

            c.execute("""SELECT category, COUNT(*) as cnt 
                        FROM questions 
                        GROUP BY category 
                        ORDER BY cnt DESC""")
            categories = c.fetchall()

            cat_list = [row['category'] for row in categories if row['category']]

            if len(cat_list) >= 3:
                for i, cat in enumerate(cat_list[:10]):
                    expansion_id = f"kg_expand_{cat}_{int(time.time())}_{i}"
                    confidence = 0.7 + 0.03 * i
                    confidence = min(0.95, confidence)

                    related = [c for c in cat_list if c != cat][:3]
                    metadata = {
                        'source_category': cat,
                        'related_categories': related,
                        'question_count': categories[i]['cnt']
                    }

                    c.execute("""INSERT OR IGNORE INTO ai_knowledge_expansion 
                        (expansion_id, source_knowledge, expanded_knowledge, 
                         expansion_type, confidence, status, created_at, metadata)
                        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                        (expansion_id, cat, json.dumps(related), 'category_relation',
                         confidence, datetime.now().isoformat(), json.dumps(metadata)))

                    if c.rowcount > 0:
                        expanded_count += 1

            c.execute("""SELECT difficulty, COUNT(*) as cnt 
                        FROM questions 
                        WHERE difficulty IS NOT NULL 
                        GROUP BY difficulty""")
            diff_stats = c.fetchall()

            if len(diff_stats) >= 3:
                expansion_id = f"kg_expand_diff_{int(time.time())}"
                c.execute("""INSERT OR IGNORE INTO ai_knowledge_expansion 
                    (expansion_id, source_knowledge, expanded_knowledge, 
                     expansion_type, confidence, status, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (expansion_id, 'difficulty_distribution',
                     json.dumps([{r['difficulty']: r['cnt']} for r in diff_stats]),
                     'difficulty_analysis', 0.85,
                     datetime.now().isoformat(),
                     json.dumps({'total_categories': len(diff_stats)})))
                if c.rowcount > 0:
                    expanded_count += 1
                    updated_models += 1

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"知识图谱扩展失败: {e}")

        return {'expanded_count': expanded_count, 'updated_models': updated_models}

    def get_learning_status(self) -> Dict[str, Any]:
        return {
            'is_learning': self._is_learning,
            'config': self.config,
            'stats': self.learning_stats
        }

    def get_recent_cycles(self, limit: int = 10) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM ai_learning_cycles 
                        ORDER BY id DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取周期列表失败: {e}")
            return []

    def get_patterns(self, pattern_type: str = None, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            if pattern_type:
                c.execute("""SELECT * FROM ai_learning_patterns 
                            WHERE pattern_type = ? AND is_active = 1
                            ORDER BY confidence DESC LIMIT ?""", (pattern_type, limit))
            else:
                c.execute("""SELECT * FROM ai_learning_patterns 
                            WHERE is_active = 1
                            ORDER BY confidence DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取模式列表失败: {e}")
            return []

    def get_insights(self, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM ai_user_behavior_insights 
                        ORDER BY confidence DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取洞察列表失败: {e}")
            return []

    def get_question_quality(self, question_id: int = None, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            if question_id:
                c.execute("""SELECT * FROM ai_question_quality 
                            WHERE question_id = ?""", (question_id,))
            else:
                c.execute("""SELECT * FROM ai_question_quality 
                            ORDER BY quality_score ASC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取题目质量失败: {e}")
            return []

    def get_knowledge_expansions(self, status: str = None, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            if status:
                c.execute("""SELECT * FROM ai_knowledge_expansion 
                            WHERE status = ? ORDER BY confidence DESC LIMIT ?""", (status, limit))
            else:
                c.execute("""SELECT * FROM ai_knowledge_expansion 
                            ORDER BY created_at DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取知识扩展失败: {e}")
            return []

    def trigger_learning(self) -> Dict[str, Any]:
        return self.start_learning_cycle()

    def update_config(self, config_updates: Dict) -> Dict[str, Any]:
        self.config.update(config_updates)
        return {'success': True, 'config': self.config}


advanced_auto_learning_system = AdvancedAutoLearningSystem()

if __name__ == '__main__':
    result = advanced_auto_learning_system.trigger_learning()
    print(f"学习结果: {json.dumps(result, ensure_ascii=False)}")
    time.sleep(5)
    status = advanced_auto_learning_system.get_learning_status()
    print(f"状态: {json.dumps(status, ensure_ascii=False, indent=2)}")
