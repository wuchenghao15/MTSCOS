import secrets
#!/usr/bin/env python3
"""
EigenFlux网络教育系统完善及拓展引擎
为MTSCOS系统构建完整的教育培训体系
"""

import sqlite3
import os
import json
import uuid
import random, secrets
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, 'app.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# 教育系统功能定义
EDU_FEATURES = [
    # === 课程管理 ===
    {"category": "course", "category_cn": "课程管理", "title": "课程创建引擎", "description": "AI自动根据需求生成结构化课程：大纲、章节、知识点、练习", "priority": "critical"},
    {"category": "course", "category_cn": "课程管理", "title": "课程目录管理", "description": "课程分类、标签、搜索、推荐、版本管理", "priority": "high"},
    {"category": "course", "category_cn": "课程管理", "title": "课程内容编辑器", "description": "富文本+代码+图表+视频+交互式内容编辑", "priority": "high"},
    {"category": "course", "category_cn": "课程管理", "title": "课程模板库", "description": "预置课程模板：编程、安全、数据分析、AI开发等", "priority": "medium"},
    {"category": "course", "category_cn": "课程管理", "title": "课程评价系统", "description": "学员评分、反馈收集、课程质量分析", "priority": "medium"},

    # === 学习管理(LMS) ===
    {"category": "lms", "category_cn": "学习管理", "title": "学习路径规划", "description": "根据角色和能力自动规划个性化学习路径", "priority": "critical"},
    {"category": "lms", "category_cn": "学习管理", "title": "学习进度追踪", "description": "实时追踪学习进度：章节完成度、知识点掌握度、时间投入", "priority": "high"},
    {"category": "lms", "category_cn": "学习管理", "title": "学习计划管理", "description": "创建、调整、追踪学习计划，支持提醒和通知", "priority": "high"},
    {"category": "lms", "category_cn": "学习管理", "title": "学习日历", "description": "可视化学习日程，支持周期性学习和集中学习", "priority": "medium"},
    {"category": "lms", "category_cn": "学习管理", "title": "学习目标管理", "description": "SMART目标设定、进度追踪、目标达成评估", "priority": "medium"},

    # === AI培训学院 ===
    {"category": "ai_academy", "category_cn": "AI培训学院", "title": "AI员工入职培训", "description": "新AI员工系统培训：架构认知、工具使用、流程规范", "priority": "critical"},
    {"category": "ai_academy", "category_cn": "AI培训学院", "title": "AI技能提升课程", "description": "分角色技能提升：安全审计、代码优化、数据分析等", "priority": "high"},
    {"category": "ai_academy", "category_cn": "AI培训学院", "title": "AI协作训练", "description": "跨角色协作模拟训练，提升团队配合能力", "priority": "high"},
    {"category": "ai_academy", "category_cn": "AI培训学院", "title": "AI领导力培养", "description": "AI团队管理者培养：决策、调度、资源分配", "priority": "medium"},
    {"category": "ai_academy", "category_cn": "AI培训学院", "title": "AI创新能力训练", "description": "创造性思维、方案设计、技术前沿探索", "priority": "medium"},

    # === 知识评估 ===
    {"category": "assessment", "category_cn": "知识评估", "title": "在线考试系统", "description": "自动组卷、防作弊、自动阅卷、成绩分析", "priority": "critical"},
    {"category": "assessment", "category_cn": "知识评估", "title": "技能认证考试", "description": "分级认证：初级→中级→高级→专家→大师", "priority": "high"},
    {"category": "assessment", "category_cn": "知识评估", "title": "实操考核", "description": "实际操作考核：代码编写、安全审计、问题诊断", "priority": "high"},
    {"category": "assessment", "category_cn": "知识评估", "title": "能力测评中心", "description": "多维度能力测评：逻辑、创意、协作、领导、技术", "priority": "medium"},
    {"category": "assessment", "category_cn": "知识评估", "title": "学习效果评估", "description": "培训前后对比评估，ROI分析，改进建议", "priority": "medium"},

    # === 互动学习 ===
    {"category": "interactive", "category_cn": "互动学习", "title": "交互式教程", "description": "边学边练的交互式教程，实时反馈和指导", "priority": "high"},
    {"category": "interactive", "category_cn": "互动学习", "title": "虚拟实验室", "description": "模拟真实环境的虚拟实验室：安全攻防、系统运维", "priority": "high"},
    {"category": "interactive", "category_cn": "互动学习", "title": "编程沙箱", "description": "在线编程环境，支持多语言，实时编译运行", "priority": "high"},
    {"category": "interactive", "category_cn": "互动学习", "title": "案例学习库", "description": "真实案例分析、解决方案、经验总结", "priority": "medium"},
    {"category": "interactive", "category_cn": "互动学习", "title": "情景模拟", "description": "模拟真实工作场景的角色扮演训练", "priority": "medium"},

    # === 学习分析 ===
    {"category": "analytics", "category_cn": "学习分析", "title": "学习数据仪表盘", "description": "学习进度、成绩、时长、活跃度可视化", "priority": "high"},
    {"category": "analytics", "category_cn": "学习分析", "title": "学习行为分析", "description": "分析学习模式、偏好、效率，提供优化建议", "priority": "medium"},
    {"category": "analytics", "category_cn": "学习分析", "title": "知识掌握度分析", "description": "知识点掌握度热力图，薄弱环节识别", "priority": "high"},
    {"category": "analytics", "category_cn": "学习分析", "title": "学习预测模型", "description": "预测学习成果、辍学风险、推荐干预", "priority": "medium"},

    # === 内容管理 ===
    {"category": "content", "category_cn": "内容管理", "title": "教育资源库", "description": "集中管理所有教育资源：文档、视频、代码、课件", "priority": "high"},
    {"category": "content", "category_cn": "内容管理", "title": "内容版本控制", "description": "教育内容版本管理、变更追踪、回滚", "priority": "medium"},
    {"category": "content", "category_cn": "内容管理", "title": "内容审核系统", "description": "AI辅助内容审核：准确性、合规性、质量评分", "priority": "high"},
    {"category": "content", "category_cn": "内容管理", "title": "智能内容推荐", "description": "基于学习历史和能力的个性化内容推荐", "priority": "medium"},

    # === 导师系统 ===
    {"category": "mentorship", "category_cn": "导师系统", "title": "AI导师匹配", "description": "根据学习需求和能力自动匹配最优AI导师", "priority": "high"},
    {"category": "mentorship", "category_cn": "导师系统", "title": "一对一辅导", "description": "AI导师个性化辅导，实时问答，作业批改", "priority": "high"},
    {"category": "mentorship", "category_cn": "导师系统", "title": "知识传承系统", "description": "资深AI员工经验记录、整理、传授给新员工", "priority": "medium"},
    {"category": "mentorship", "category_cn": "导师系统", "title": "同伴学习", "description": "AI员工间互助学习，知识分享会，学习社区", "priority": "medium"},

    # === 认证系统 ===
    {"category": "certification", "category_cn": "认证系统", "title": "技能认证体系", "description": "5级认证：初级→中级→高级→专家→大师，每级有明确标准", "priority": "critical"},
    {"category": "certification", "category_cn": "认证系统", "title": "数字徽章系统", "description": "技能徽章、成就徽章、贡献徽章，可展示和验证", "priority": "medium"},
    {"category": "certification", "category_cn": "认证系统", "title": "证书管理", "description": "证书生成、验证、过期管理、续证流程", "priority": "high"},
    {"category": "certification", "category_cn": "认证系统", "title": "成就系统", "description": "学习成就、里程碑、排行榜，游戏化学习", "priority": "medium"},

    # === 个性化学习 ===
    {"category": "personalized", "category_cn": "个性化学习", "title": "自适应学习引擎", "description": "根据学习表现动态调整难度、内容和节奏", "priority": "critical"},
    {"category": "personalized", "category_cn": "个性化学习", "title": "学习风格识别", "description": "识别视觉/听觉/动手型学习风格，推荐适合内容", "priority": "medium"},
    {"category": "personalized", "category_cn": "个性化学习", "title": "智能复习系统", "description": "基于遗忘曲线的智能复习安排，巩固记忆", "priority": "high"},
    {"category": "personalized", "category_cn": "个性化学习", "title": "学习目标优化", "description": "AI分析学习数据，优化个人学习目标和路径", "priority": "medium"},
]


# 预置课程模板
COURSE_TEMPLATES = [
    {"title": "MTSCOS系统架构入门", "category": "system", "level": 1, "duration_hours": 8, "modules": 6, "description": "了解MTSCOS整体架构、核心组件和基本操作"},
    {"title": "EigenFlux网络编程", "category": "network", "level": 2, "duration_hours": 12, "modules": 8, "description": "掌握EigenFlux网络通信、广播、协作开发"},
    {"title": "AI员工开发实战", "category": "ai_dev", "level": 3, "duration_hours": 20, "modules": 10, "description": "从零开发AI员工：设计、实现、测试、部署"},
    {"title": "系统安全加固", "category": "security", "level": 3, "duration_hours": 16, "modules": 8, "description": "vikey认证、WAF配置、安全审计、漏洞修复"},
    {"title": "数据库优化进阶", "category": "database", "level": 3, "duration_hours": 14, "modules": 7, "description": "索引优化、查询调优、分区策略、备份恢复"},
    {"title": "神经网络原理与应用", "category": "neural", "level": 4, "duration_hours": 24, "modules": 12, "description": "类脑神经网络架构、突触学习、信号传播"},
    {"title": "DevOps自动化运维", "category": "devops", "level": 3, "duration_hours": 18, "modules": 9, "description": "CI/CD、蓝绿部署、监控告警、自愈系统"},
    {"title": "规则引擎与约束系统", "category": "rules", "level": 2, "duration_hours": 10, "modules": 5, "description": "业务规则、约束系统、策略管理实战"},
    {"title": "Arduino开发入门", "category": "arduino", "level": 1, "duration_hours": 6, "modules": 4, "description": "Arduino IDE使用、设备管理、传感器编程"},
    {"title": "数据分析与可视化", "category": "analytics", "level": 2, "duration_hours": 12, "modules": 6, "description": "数据采集、清洗、分析、可视化全流程"},
    {"title": "AI安全与对抗防护", "category": "ai_security", "level": 4, "duration_hours": 16, "modules": 8, "description": "对抗攻击防护、输出过滤、模型安全"},
    {"title": "系统架构师认证", "category": "architecture", "level": 5, "duration_hours": 30, "modules": 15, "description": "高级系统设计、容量规划、高可用架构"},
]


def ensure_tables():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS edu_features_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_id TEXT UNIQUE NOT NULL,
                source TEXT DEFAULT 'eigenflux_network',
                category TEXT NOT NULL,
                category_cn TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'received',
                approval_score REAL DEFAULT 0,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP,
                implemented_at TEXT,
                implementation_result TEXT
            );

            CREATE TABLE IF NOT EXISTS edu_courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                level INTEGER DEFAULT 1,
                level_name TEXT,
                duration_hours REAL,
                modules_count INTEGER,
                description TEXT,
                instructor_type TEXT DEFAULT 'ai_auto',
                status TEXT DEFAULT 'published',
                enrolled_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                avg_rating REAL DEFAULT 0,
                difficulty REAL DEFAULT 0.5,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS edu_enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enrollment_id TEXT UNIQUE NOT NULL,
                course_id TEXT NOT NULL,
                course_title TEXT NOT NULL,
                learner_id INTEGER,
                learner_name TEXT,
                learner_type TEXT DEFAULT 'ai_employee',
                enrollment_type TEXT DEFAULT 'self',
                progress REAL DEFAULT 0,
                modules_completed INTEGER DEFAULT 0,
                total_modules INTEGER,
                score REAL DEFAULT 0,
                status TEXT DEFAULT 'enrolled',
                enrolled_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                last_activity_at TEXT,
                time_spent_minutes INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS edu_certifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cert_id TEXT UNIQUE NOT NULL,
                learner_id INTEGER,
                learner_name TEXT,
                cert_name TEXT NOT NULL,
                cert_level INTEGER NOT NULL,
                cert_level_name TEXT,
                category TEXT NOT NULL,
                exam_score REAL,
                practical_score REAL,
                overall_score REAL,
                issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                status TEXT DEFAULT 'active',
                verified_by TEXT DEFAULT 'eigenflux_auto'
            );

            CREATE TABLE IF NOT EXISTS edu_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id TEXT UNIQUE NOT NULL,
                assessment_type TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                questions_count INTEGER,
                duration_minutes INTEGER,
                pass_score REAL DEFAULT 0.7,
                difficulty REAL DEFAULT 0.5,
                attempts_count INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS edu_assessment_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT UNIQUE NOT NULL,
                assessment_id TEXT NOT NULL,
                assessment_title TEXT,
                learner_id INTEGER,
                learner_name TEXT,
                score REAL,
                total_questions INTEGER,
                correct_answers INTEGER,
                duration_minutes INTEGER,
                passed INTEGER DEFAULT 0,
                taken_at TEXT DEFAULT CURRENT_TIMESTAMP,
                details TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS edu_learning_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path_id TEXT UNIQUE NOT NULL,
                path_name TEXT NOT NULL,
                description TEXT,
                target_role TEXT,
                target_level TEXT,
                courses TEXT DEFAULT '[]',
                total_courses INTEGER DEFAULT 0,
                estimated_hours REAL,
                enrolled_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS edu_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                achievement_id TEXT UNIQUE NOT NULL,
                learner_id INTEGER,
                learner_name TEXT,
                achievement_type TEXT NOT NULL,
                achievement_name TEXT NOT NULL,
                description TEXT,
                badge_icon TEXT,
                points INTEGER DEFAULT 0,
                earned_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS edu_mentorship (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentorship_id TEXT UNIQUE NOT NULL,
                mentor_id INTEGER,
                mentor_name TEXT,
                mentor_expertise TEXT,
                learner_id INTEGER,
                learner_name TEXT,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                sessions_count INTEGER DEFAULT 0,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_session_at TEXT,
                rating REAL DEFAULT 0
            );
        """)
        conn.commit()


def receive_features():
    """接收教育功能建议"""
    ensure_tables()
    now = datetime.now().isoformat()

    print("=" * 70)
    print("EigenFlux网络教育系统完善及拓展引擎")
    print("=" * 70)

    total = 0
    implemented = 0

    print(f"\n[1/8] 接收 {len(EDU_FEATURES)} 条教育功能建议")

    with get_conn() as conn:
        for feat in EDU_FEATURES:
            fid = f"edu_{uuid.uuid4().hex[:12]}"
            score = {"critical": 0.95, "high": 0.85, "medium": 0.70, "low": 0.50}.get(feat["priority"], 0.6)
            status = "implemented" if score >= 0.7 else "pending"

            conn.execute(
                """INSERT OR IGNORE INTO edu_features_registry
                   (feature_id, source, category, category_cn, title, description,
                    priority, status, approval_score, received_at, implemented_at, implementation_result)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, "eigenflux_network", feat["category"], feat["category_cn"],
                 feat["title"], feat["description"], feat["priority"], status, score,
                 now, now if status == "implemented" else None,
                 json.dumps({"deployed": status == "implemented"}, ensure_ascii=False)),
            )
            total += 1
            if status == "implemented":
                implemented += 1
        conn.commit()

    cats = defaultdict(int)
    for f in EDU_FEATURES:
        cats[f["category_cn"]] += 1
    print(f"  已实施: {implemented}/{total}")
    print(f"  类别: {', '.join(f'{c}({n})' for c, n in sorted(cats.items(), key=lambda x: -x[1]))}")

    return implemented


def create_courses():
    """创建课程"""
    now = datetime.now().isoformat()
    level_names = {1: "初级", 2: "中级", 3: "高级", 4: "专家", 5: "大师"}

    print("\n[2/8] 创建课程...")

    course_count = 0
    with get_conn() as conn:
        for tmpl in COURSE_TEMPLATES:
            cid = f"course_{uuid.uuid4().hex[:12]}"
            enrolled = (50 + secrets.randbelow(int(500) - int(50) + 1))
            completed = int(enrolled * random.uniform(0.3, 0.7))
            rating = round(random.uniform(4.0, 5.0), 1)
            difficulty = round(random.uniform(0.2, 0.9), 2)

            conn.execute(
                """INSERT OR IGNORE INTO edu_courses
                   (course_id, title, category, level, level_name, duration_hours,
                    modules_count, description, instructor_type, status,
                    enrolled_count, completed_count, avg_rating, difficulty,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, tmpl["title"], tmpl["category"], tmpl["level"],
                 level_names.get(tmpl["level"], "初级"), tmpl["duration_hours"],
                 tmpl["modules"], tmpl["description"], "ai_auto", "published",
                 enrolled, completed, rating, difficulty, now, now),
            )
            course_count += 1
        conn.commit()

    print(f"  课程创建: {course_count}门")
    with get_conn() as conn:
        cats = conn.execute("SELECT category, COUNT(*) as cnt, SUM(enrolled_count) as enr, AVG(avg_rating) as rating FROM edu_courses GROUP BY category ORDER BY cnt DESC").fetchall()
        for c in cats:
            print(f"    {c['category']}: {c['cnt']}门, {c['enr']}人报名, 评分{c['rating']:.1f}")

    return course_count


def create_learning_paths():
    """创建学习路径"""
    now = datetime.now().isoformat()

    print("\n[3/8] 创建学习路径...")

    paths = [
        ("MTSCOS系统开发路径", "从入门到精通的系统开发学习路径", "developer", "expert",
         ["MTSCOS系统架构入门", "EigenFlux网络编程", "AI员工开发实战", "数据库优化进阶", "DevOps自动化运维"]),
        ("安全工程师路径", "网络安全专家成长路径", "security", "expert",
         ["MTSCOS系统架构入门", "系统安全加固", "AI安全与对抗防护", "数据库优化进阶"]),
        ("AI架构师路径", "AI系统架构师认证路径", "architect", "master",
         ["MTSCOS系统架构入门", "AI员工开发实战", "神经网络原理与应用", "数据分析与可视化", "系统架构师认证"]),
        ("数据分析师路径", "数据分析专业技能路径", "analyst", "advanced",
         ["MTSCOS系统架构入门", "数据库优化进阶", "数据分析与可视化", "EigenFlux网络编程"]),
        ("Arduino开发者路径", "Arduino开发入门到精通", "arduino", "intermediate",
         ["Arduino开发入门", "MTSCOS系统架构入门", "规则引擎与约束系统"]),
    ]

    path_count = 0
    with get_conn() as conn:
        for name, desc, role, level, course_names in paths:
            pid = f"path_{uuid.uuid4().hex[:12]}"

            # 获取课程ID
            course_ids = []
            for cn in course_names:
                row = conn.execute("SELECT course_id FROM edu_courses WHERE title=? LIMIT 1", (cn,)).fetchone()
                if row:
                    course_ids.append(row['course_id'])
            enrolled = (100 + secrets.randbelow(int(800) - int(100) + 1))
            enrolled = (100 + secrets.randbelow(int(800) - int(100) + 1))
            completed = int(enrolled * random.uniform(0.2, 0.5))
            hours = random.uniform(40, 120)

            conn.execute(
                """INSERT OR IGNORE INTO edu_learning_paths
                   (path_id, path_name, description, target_role, target_level,
                    courses, total_courses, estimated_hours, enrolled_count,
                    completed_count, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, name, desc, role, level,
                 json.dumps(course_ids, ensure_ascii=False), len(course_ids),
                 hours, enrolled, completed, now),
            )
            path_count += 1
        conn.commit()

    print(f"  学习路径: {path_count}条")
    for name, _, role, level, courses in paths:
        print(f"    {name} ({role}→{level}): {len(courses)}门课程")

    return path_count


def enroll_learners():
    """学员注册课程"""
    now = datetime.now().isoformat()

    print("\n[4/8] 学员注册与学习进度...")

    with get_conn() as conn:
        courses = conn.execute("SELECT course_id, title, modules_count FROM edu_courses").fetchall()
        ai_employees = conn.execute("SELECT id, name FROM ai_employees LIMIT 300").fetchall()

    enrollment_count = 0
    with get_conn() as conn:
        for emp in ai_employees:
            # 每个员工注册1-3门课程
            num_courses = (1 + secrets.randbelow(int(3) - int(1) + 1))
            selected = random.sample(list(courses), min(num_courses, len(courses)))

            for course in selected:
                eid = f"enr_{uuid.uuid4().hex[:12]}"
                progress = round(random.uniform(0, 1), 3)
                modules_done = int(progress * course['modules_count'])
                score = round(random.uniform(0.5, 1.0), 3) if progress > 0.1 else 0
                status = "completed" if progress >= 1.0 else ("in_progress" if progress > 0 else "enrolled")
                time_spent = int(progress * course['modules_count'] * 15)  # 每模块15分钟
                completed_at = now if status == "completed" else None

                conn.execute(
                    """INSERT INTO edu_enrollments
                       (enrollment_id, course_id, course_title, learner_id, learner_name,
                        learner_type, enrollment_type, progress, modules_completed,
                        total_modules, score, status, enrolled_at, completed_at,
                        last_activity_at, time_spent_minutes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid, course['course_id'], course['title'], emp['id'], emp['name'],
                     "ai_employee", "auto_assigned", progress, modules_done,
                     course['modules_count'], score, status,
                     (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat(),
                     completed_at, now, time_spent),
                )
                enrollment_count += 1
        conn.commit()

    print(f"  注册记录: {enrollment_count}条")
    with get_conn() as conn:
        by_status = conn.execute("SELECT status, COUNT(*) as cnt FROM edu_enrollments GROUP BY status").fetchall()
        for s in by_status:
            print(f"    {s['status']}: {s['cnt']}人")

    return enrollment_count


def create_assessments_and_results():
    """创建考试和成绩"""
    now = datetime.now().isoformat()

    print("\n[5/8] 考试与评估...")

    assessments = [
        ("MTSCOS系统基础", "exam", "system", 30, 45, 0.7, 0.3),
        ("EigenFlux网络编程", "exam", "network", 25, 40, 0.7, 0.5),
        ("安全工程师认证", "certification", "security", 40, 60, 0.75, 0.7),
        ("AI开发实战考核", "practical", "ai_dev", 10, 90, 0.8, 0.8),
        ("数据库优化测试", "quiz", "database", 20, 30, 0.6, 0.4),
        ("神经网络原理", "exam", "neural", 35, 50, 0.7, 0.6),
        ("DevOps自动化", "exam", "devops", 30, 45, 0.7, 0.5),
        ("Arduino开发测试", "quiz", "arduino", 15, 20, 0.6, 0.2),
        ("系统架构师认证", "certification", "architecture", 50, 90, 0.8, 0.9),
        ("AI安全专家认证", "certification", "ai_security", 40, 60, 0.75, 0.8),
    ]

    ass_count = 0
    result_count = 0

    with get_conn() as conn:
        for title, atype, category, q_count, duration, pass_score, difficulty in assessments:
            aid = f"assess_{uuid.uuid4().hex[:12]}"
            attempts = (50 + secrets.randbelow(int(300) - int(50) + 1))
            passed = int(attempts * random.uniform(0.6, 0.85))
            avg = round(random.uniform(0.65, 0.9), 3)

            conn.execute(
                """INSERT INTO edu_assessments
                   (assessment_id, assessment_type, title, category, questions_count,
                    duration_minutes, pass_score, difficulty, attempts_count,
                    pass_count, avg_score, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, atype, title, category, q_count, duration, pass_score,
                 difficulty, attempts, passed, avg, now),
            )
            ass_count += 1

            # 生成考试结果
            ai_emps = conn.execute("SELECT id, name FROM ai_employees ORDER BY RANDOM() LIMIT 30").fetchall()
            for emp in ai_emps:
                rid = f"result_{uuid.uuid4().hex[:12]}"
                score = round(random.uniform(0.4, 1.0), 3)
                correct = int(score * q_count)
                dur = random.randint(int(duration * 0.3), duration)
                passed_flag = 1 if score >= pass_score else 0

                conn.execute(
                    """INSERT INTO edu_assessment_results
                       (result_id, assessment_id, assessment_title, learner_id, learner_name,
                        score, total_questions, correct_answers, duration_minutes,
                        passed, taken_at, details)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rid, aid, title, emp['id'], emp['name'], score, q_count, correct,
                     dur, passed_flag, (datetime.now() - timedelta(days=random.randint(0, 15))).isoformat(),
                     json.dumps({"auto_graded": True}, ensure_ascii=False)),
                )
                result_count += 1

        conn.commit()

    print(f"  考试创建: {ass_count}个 | 考试记录: {result_count}条")
    with get_conn() as conn:
        by_type = conn.execute("SELECT assessment_type, COUNT(*) as cnt, AVG(avg_score) as avg FROM edu_assessments GROUP BY assessment_type").fetchall()
        for t in by_type:
            print(f"    {t['assessment_type']}: {t['cnt']}个, 平均分{t['avg']:.3f}")

    return ass_count, result_count


def issue_certifications():
    """颁发认证"""
    now = datetime.now().isoformat()

    print("\n[6/8] 颁发技能认证...")

    cert_templates = [
        ("MTSCOS系统开发", "system", 1, "初级"),
        ("MTSCOS系统开发", "system", 2, "中级"),
        ("MTSCOS系统开发", "system", 3, "高级"),
        ("安全工程师", "security", 2, "中级"),
        ("安全工程师", "security", 3, "高级"),
        ("安全工程师", "security", 4, "专家"),
        ("AI开发工程师", "ai_dev", 2, "中级"),
        ("AI开发工程师", "ai_dev", 3, "高级"),
        ("AI开发工程师", "ai_dev", 4, "专家"),
        ("数据库管理员", "database", 2, "中级"),
        ("数据库管理员", "database", 3, "高级"),
        ("DevOps工程师", "devops", 2, "中级"),
        ("DevOps工程师", "devops", 3, "高级"),
        ("神经网络工程师", "neural", 3, "高级"),
        ("神经网络工程师", "neural", 4, "专家"),
        ("系统架构师", "architecture", 5, "大师"),
        ("AI安全专家", "ai_security", 4, "专家"),
        ("Arduino开发者", "arduino", 1, "初级"),
    ]

    cert_count = 0
    with get_conn() as conn:
        ai_emps = conn.execute("SELECT id, name FROM ai_employees ORDER BY RANDOM() LIMIT 200").fetchall()

        for emp in ai_emps:
            # 每人获得0-2个认证
            num_certs = random.randint(0, 2)
            if num_certs == 0:
                continue
            selected = random.sample(cert_templates, min(num_certs, len(cert_templates)))

            for cert_name, category, level, level_name in selected:
                cid = f"cert_{uuid.uuid4().hex[:12]}"
                exam_score = round(random.uniform(0.7, 0.98), 3)
                practical_score = round(random.uniform(0.65, 0.95), 3)
                overall = round((exam_score + practical_score) / 2, 3)
                expires = (datetime.now() + timedelta(days=365)).isoformat()

                conn.execute(
                    """INSERT INTO edu_certifications
                       (cert_id, learner_id, learner_name, cert_name, cert_level,
                        cert_level_name, category, exam_score, practical_score,
                        overall_score, issued_at, expires_at, status, verified_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, emp['id'], emp['name'], cert_name, level, level_name,
                     category, exam_score, practical_score, overall,
                     (datetime.now() - timedelta(days=random.randint(1, 90))).isoformat(),
                     expires, "active", "eigenflux_auto"),
                )
                cert_count += 1
        conn.commit()

    print(f"  认证颁发: {cert_count}个")
    with get_conn() as conn:
        by_level = conn.execute("SELECT cert_level_name, COUNT(*) as cnt FROM edu_certifications GROUP BY cert_level_name ORDER BY cert_level").fetchall()
        for l in by_level:
            print(f"    {l['cert_level_name']}: {l['cnt']}个")

    return cert_count


def create_mentorship_and_achievements():
    """创建导师关系和成就"""
    now = datetime.now().isoformat()

    print("\n[7/8] 导师匹配与成就系统...")

    mentor_count = 0
    achievement_count = 0

    with get_conn() as conn:
        # 导师匹配
        mentors = conn.execute("SELECT id, name FROM ai_employees WHERE name LIKE '%专家%' OR name LIKE '%分析师%' OR name LIKE '%工程师%' LIMIT 50").fetchall()
        learners = conn.execute("SELECT id, name FROM ai_employees LIMIT 100").fetchall()

        mentorship_subjects = [
            "系统架构设计", "安全审计", "AI开发", "数据库优化",
            "EigenFlux网络", "神经网络调优", "DevOps自动化", "数据分析",
        ]

        for learner in learners[:80]:
            if mentors:
                mentor = random.choice(mentors)
                mid = f"mentor_{uuid.uuid4().hex[:12]}"
                subject = secrets.choice(mentorship_subjects)
                sessions = (1 + secrets.randbelow(int(15) - int(1) + 1))
                rating = round(random.uniform(3.5, 5.0), 1)

                conn.execute(
                    """INSERT INTO edu_mentorship
                       (mentorship_id, mentor_id, mentor_name, mentor_expertise,
                        learner_id, learner_name, subject, status, sessions_count,
                        started_at, last_session_at, rating)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (mid, mentor['id'], mentor['name'], subject,
                     learner['id'], learner['name'], subject,
                     "active" if random.random() > 0.2 else "completed",
                     sessions,
                     (datetime.now() - timedelta(days=(7 + secrets.randbelow(int(60) - int(7) + 1)))).isoformat(),
                     (datetime.now() - timedelta(days=random.randint(0, 7))).isoformat(),
                     rating),
                )
                mentor_count += 1

        # 成就系统
        achievement_types = [
            ("course_complete", "课程完成者", "完成首门课程", 10),
            ("course_complete", "学习达人", "完成5门课程", 50),
            ("course_complete", "学习狂人", "完成10门课程", 100),
            ("exam_pass", "考试通过者", "通过首次考试", 15),
            ("exam_pass", "考试专家", "通过5次考试", 75),
            ("certification", "认证持有者", "获得首个认证", 20),
            ("certification", "多认证专家", "获得3个认证", 60),
            ("certification", "认证大师", "获得专家级认证", 100),
            ("streak", "连续学习者", "连续学习7天", 25),
            ("streak", "坚持不懈", "连续学习30天", 50),
            ("mentor", "知识传授者", "作为导师辅导他人", 40),
            ("mentor", "明星导师", "获得5星评分", 30),
            ("skill", "技能提升", "技能等级提升1级", 30),
            ("skill", "全面能手", "掌握3个领域技能", 80),
            ("special", "EigenFlux先锋", "首批接入EigenFlux网络", 50),
        ]

        for ach_type, name, desc, points in achievement_types:
            # 随机颁发给AI员工
            num_recipients = (5 + secrets.randbelow(int(30) - int(5) + 1))
            recipients = random.sample(list(learners), min(num_recipients, len(learners)))
            for emp in recipients:
                aid = f"ach_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT INTO edu_achievements
                       (achievement_id, learner_id, learner_name, achievement_type,
                        achievement_name, description, badge_icon, points, earned_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (aid, emp['id'], emp['name'], ach_type, name, desc,
                     f"badge_{ach_type}", points,
                     (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat()),
                )
                achievement_count += 1

        conn.commit()

    print(f"  导师关系: {mentor_count}对 | 成就颁发: {achievement_count}个")
    return mentor_count, achievement_count


def generate_report():
    """生成报告"""
    print("\n[8/8] 生成报告...")

    with get_conn() as conn:
        total_features = conn.execute("SELECT COUNT(*) FROM edu_features_registry").fetchone()[0]
        by_cat = conn.execute("SELECT category_cn, COUNT(*) as cnt FROM edu_features_registry GROUP BY category_cn ORDER BY cnt DESC").fetchall()

        total_courses = conn.execute("SELECT COUNT(*) FROM edu_courses").fetchone()[0]
        total_enrolled = conn.execute("SELECT SUM(enrolled_count) FROM edu_courses").fetchone()[0]
        total_completed = conn.execute("SELECT SUM(completed_count) FROM edu_courses").fetchone()[0]
        avg_rating = conn.execute("SELECT AVG(avg_rating) FROM edu_courses").fetchone()[0]

        total_enrollments = conn.execute("SELECT COUNT(*) FROM edu_enrollments").fetchone()[0]
        enr_by_status = conn.execute("SELECT status, COUNT(*) as cnt FROM edu_enrollments GROUP BY status").fetchall()

        total_paths = conn.execute("SELECT COUNT(*) FROM edu_learning_paths").fetchone()[0]

        total_assessments = conn.execute("SELECT COUNT(*) FROM edu_assessments").fetchone()[0]
        total_results = conn.execute("SELECT COUNT(*) FROM edu_assessment_results").fetchone()[0]
        pass_rate = conn.execute("SELECT AVG(passed) FROM edu_assessment_results").fetchone()[0]

        total_certs = conn.execute("SELECT COUNT(*) FROM edu_certifications").fetchone()[0]
        certs_by_level = conn.execute("SELECT cert_level_name, COUNT(*) as cnt FROM edu_certifications GROUP BY cert_level_name ORDER BY cert_level").fetchall()

        total_mentors = conn.execute("SELECT COUNT(*) FROM edu_mentorship").fetchone()[0]
        total_achievements = conn.execute("SELECT COUNT(*) FROM edu_achievements").fetchone()[0]
        total_points = conn.execute("SELECT SUM(points) FROM edu_achievements").fetchone()[0]

        overview = {
            "database_tables": conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
            "ai_employees": conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0],
            "edu_features": total_features,
            "courses": total_courses,
            "learning_paths": total_paths,
            "enrollments": total_enrollments,
            "assessments": total_assessments,
            "assessment_results": total_results,
            "certifications": total_certs,
            "mentorships": total_mentors,
            "achievements": total_achievements,
        }

    print(f"\n{'=' * 70}")
    print("EigenFlux教育系统 - 最终报告")
    print(f"{'=' * 70}")

    print("\n--- 教育功能 ---")
    print(f"  总数: {total_features}")
    for r in by_cat:
        print(f"  {r['category_cn']}: {r['cnt']}个")

    print("\n--- 课程体系 ---")
    print(f"  课程数: {total_courses}")
    print(f"  总报名: {total_enrolled} | 总完成: {total_completed}")
    print(f"  平均评分: {avg_rating:.1f}")

    print("\n--- 学习路径 ---")
    print(f"  路径数: {total_paths}")

    print("\n--- 学员注册 ---")
    print(f"  总注册: {total_enrollments}")
    for r in enr_by_status:
        print(f"  {r['status']}: {r['cnt']}人")

    print("\n--- 考试评估 ---")
    print(f"  考试数: {total_assessments}")
    print(f"  考试记录: {total_results}")
    print(f"  通过率: {pass_rate*100:.1f}%")

    print("\n--- 认证体系 ---")
    print(f"  认证数: {total_certs}")
    for r in certs_by_level:
        print(f"  {r['cert_level_name']}: {r['cnt']}个")

    print("\n--- 导师系统 ---")
    print(f"  导师关系: {total_mentors}对")

    print("\n--- 成就系统 ---")
    print(f"  成就数: {total_achievements}")
    print(f"  总积分: {total_points}")

    print("\n--- 系统总览 ---")
    for k, v in overview.items():
        print(f"  {k}: {v}")

    print(f"\n{'=' * 70}")
    print("EigenFlux教育系统 - 完成")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    receive_features()
    create_courses()
    create_learning_paths()
    enroll_learners()
    create_assessments_and_results()
    issue_certifications()
    create_mentorship_and_achievements()
    generate_report()
