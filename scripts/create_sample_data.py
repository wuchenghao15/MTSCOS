#!/usr/bin/env python3
"""
创建示例业务数据
为AI功能提供真实的数据基础
"""

import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = 'app.db'

def create_exam_results():
    """创建考试结果数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM exams WHERE status = "published"')
    exam_ids = [r[0] for r in cursor.fetchall()]
    
    cursor.execute('SELECT id FROM users WHERE role = "user" AND is_active = 1')
    user_ids = [r[0] for r in cursor.fetchall()]
    
    if not exam_ids or not user_ids:
        logger.info("没有找到考试或用户数据")
        conn.close()
        return
    
    subjects = ['数学', '英语', '语文', '物理', '化学', '生物']
    for user_id in user_ids:
        for exam_id in exam_ids[:3]:
            score = random.randint(45, 95)
            completed_at = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO exam_results (user_id, exam_id, score, total_score, status, completed_at)
                VALUES (?, ?, ?, 100, 'completed', ?)
            ''', (user_id, exam_id, score, completed_at))
    
    conn.commit()
    count = cursor.execute('SELECT COUNT(*) FROM exam_results').fetchone()[0]
    logger.info(f'创建考试结果: {count} 条')
    conn.close()

def create_wrong_questions():
    """创建错题记录数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE role = "user" AND is_active = 1')
    user_ids = [str(r[0]) for r in cursor.fetchall()]
    
    wrong_question_templates = [
        ('一元二次方程求解', '数学'),
        ('三角函数恒等式', '数学'),
        ('导数应用', '数学'),
        ('概率计算', '数学'),
        ('立体几何', '数学'),
        ('阅读理解推断题', '英语'),
        ('完形填空', '英语'),
        ('语法填空', '英语'),
        ('物理力学', '物理'),
        ('电路分析', '物理'),
        ('化学方程式配平', '化学'),
        ('有机化学', '化学'),
        ('文言文翻译', '语文'),
        ('诗歌鉴赏', '语文'),
        ('现代文阅读', '语文')
    ]
    
    for user_id in user_ids:
        num_wrong = random.randint(5, 15)
        selected = random.sample(wrong_question_templates, min(num_wrong, len(wrong_question_templates)))
        
        for question_content, subject in selected:
            wrong_count = random.randint(1, 5)
            last_wrong_date = (datetime.now() - timedelta(days=random.randint(1, 14))).strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO wrong_questions (question_content, subject, user_id, wrong_count, last_wrong_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (question_content, subject, user_id, wrong_count, last_wrong_date))
    
    conn.commit()
    count = cursor.execute('SELECT COUNT(*) FROM wrong_questions').fetchone()[0]
    logger.info(f'创建错题记录: {count} 条')
    conn.close()

def create_homework_tables():
    """创建作业相关表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT,
            description TEXT,
            due_date TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS homework_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            homework_id INTEGER,
            user_id INTEGER,
            content TEXT,
            score REAL,
            feedback TEXT,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (homework_id) REFERENCES homework(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    logger.info('创建作业表完成')
    conn.close()

def create_homework_data():
    """创建作业数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE role = "teacher" OR role = "admin"')
    teacher_ids = [r[0] for r in cursor.fetchall()]
    if not teacher_ids:
        teacher_ids = [3]
    
    cursor.execute('SELECT id FROM users WHERE role = "user" AND is_active = 1')
    user_ids = [r[0] for r in cursor.fetchall()]
    
    homeworks = [
        ('一元二次方程练习', '数学', '完成课后习题1-10题', teacher_ids[0]),
        ('三角函数复习', '数学', '复习三角函数公式，完成练习题', teacher_ids[0]),
        ('英语阅读理解', '英语', '阅读三篇文章并回答问题', teacher_ids[0]),
        ('物理力学实验报告', '物理', '完成力学实验报告', teacher_ids[0]),
        ('化学方程式', '化学', '配平20个化学方程式', teacher_ids[0]),
        ('语文作文', '语文', '写一篇800字作文', teacher_ids[0])
    ]
    
    for title, subject, description, created_by in homeworks:
        due_date = (datetime.now() + timedelta(days=random.randint(1, 7))).strftime('%Y-%m-%d')
        cursor.execute('''
            INSERT INTO homework (title, subject, description, due_date, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, subject, description, due_date, created_by))
        homework_id = cursor.lastrowid
        
        for user_id in user_ids[:3]:
            content = f'作业内容：{title} - 用户{user_id}'
            score = random.randint(60, 98)
            feedback = ['完成良好', '需要改进', '优秀', '继续努力'][random.randint(0, 3)]
            
            cursor.execute('''
                INSERT INTO homework_submissions (homework_id, user_id, content, score, feedback)
                VALUES (?, ?, ?, ?, ?)
            ''', (homework_id, user_id, content, score, feedback))
    
    conn.commit()
    count = cursor.execute('SELECT COUNT(*) FROM homework').fetchone()[0]
    subm_count = cursor.execute('SELECT COUNT(*) FROM homework_submissions').fetchone()[0]
    logger.info(f'创建作业: {count} 条，作业提交: {subm_count} 条')
    conn.close()

def create_learning_records():
    """创建学习记录表和数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER,
            topic TEXT,
            duration INTEGER,
            progress REAL,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    cursor.execute('SELECT id FROM users WHERE role = "user" AND is_active = 1')
    user_ids = [r[0] for r in cursor.fetchall()]
    
    cursor.execute('SELECT id FROM courses WHERE status = "active"')
    course_ids = [r[0] for r in cursor.fetchall()]
    
    topics = {
        '数学': ['函数基础', '导数', '积分', '概率统计', '线性代数'],
        '英语': ['词汇', '语法', '阅读', '写作', '听力'],
        '物理': ['力学', '电磁学', '光学', '热学', '量子力学'],
        '化学': ['无机化学', '有机化学', '分析化学', '物理化学'],
        '语文': ['文言文', '现代文', '诗歌', '写作']
    }
    
    for user_id in user_ids:
        for course_id in course_ids[:2]:
            cursor.execute('SELECT name FROM courses WHERE id = ?', (course_id,))
            course_name = cursor.fetchone()[0]
            subject = course_name.split()[0] if ' ' in course_name else '数学'
            
            for topic in topics.get(subject, topics['数学'])[:3]:
                duration = random.randint(15, 120)
                progress = random.uniform(0.3, 1.0)
                completed = 1 if progress >= 0.9 else 0
                
                cursor.execute('''
                    INSERT INTO learning_records (user_id, course_id, topic, duration, progress, completed)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, course_id, topic, duration, progress, completed))
    
    conn.commit()
    count = cursor.execute('SELECT COUNT(*) FROM learning_records').fetchone()[0]
    logger.info(f'创建学习记录: {count} 条')
    conn.close()

def create_course_enrollments():
    """创建课程报名数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS course_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER,
            enrolled_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    cursor.execute('SELECT id FROM users WHERE role = "user" AND is_active = 1')
    user_ids = [r[0] for r in cursor.fetchall()]
    
    cursor.execute('SELECT id FROM courses WHERE status = "active"')
    course_ids = [r[0] for r in cursor.fetchall()]
    
    for user_id in user_ids:
        enrolled_courses = random.sample(course_ids, min(random.randint(1, 3), len(course_ids)))
        for course_id in enrolled_courses:
            cursor.execute('''
                INSERT INTO course_enrollments (user_id, course_id)
                VALUES (?, ?)
            ''', (user_id, course_id))
    
    conn.commit()
    count = cursor.execute('SELECT COUNT(*) FROM course_enrollments').fetchone()[0]
    logger.info(f'创建课程报名: {count} 条')
    conn.close()

def main():
    logger.info('=== 创建示例业务数据 ===')
    
    create_exam_results()
    create_wrong_questions()
    create_homework_tables()
    create_homework_data()
    create_learning_records()
    create_course_enrollments()
    
    logger.info('\n=== 数据创建完成 ===')

if __name__ == '__main__':
    main()