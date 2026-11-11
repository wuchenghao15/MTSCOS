#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧊 冰山 Schema Seeder — 12 张缺失表 + 智能 Seed
===============================================
数据源: mt_iceberg_content_matrix (687) + mt_skill_registry (245) + mt_lab_hr_log (12243)
        + mt_center_evolution_log (62663) + mtscos_ai_employees (23) + ai_employees (45)

用法:
  python3 engines/iceberg_schema_seeder.py --create    # 只建表
  python3 engines/iceberg_schema_seeder.py --seed      # 只 seed
  python3 engines/iceberg_schema_seeder.py --all       # 一键建表+seed
  python3 engines/iceberg_schema_seeder.py --verify    # 验证所有表状态
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from collections import Counter

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_APP_DIR, "database", "app.db")

# ─── Ollama 调用封装 ────────────────────────────────────────────────────
def ollama_generate(prompt: str, model: str = "qwen2.5:3b", timeout: int = 60) -> str:
    """调用本地 Ollama，返回纯文本回复（无 JSON 约束）"""
    try:
        r = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════
# 12 张缺失表的 DDL (含冲突处理: 空表先 DROP 再重建)
# ═══════════════════════════════════════════════════════════════════════

ICEBERG_SCHEMAS: dict[str, str] = {
    # ── AI 员工 ──────────────────────────────────────────────────
    "mt_ai_employees": """
        CREATE TABLE IF NOT EXISTS mt_ai_employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'assistant',
            center TEXT,
            status TEXT DEFAULT 'active',
            level REAL DEFAULT 1.0,
            scores_json TEXT DEFAULT '{}',
            skills_json TEXT DEFAULT '[]',
            avatar_emoji TEXT DEFAULT '🤖',
            source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
    )""",

    "mt_ai_employee_skill": """
        CREATE TABLE IF NOT EXISTS mt_ai_employee_skill (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            proficiency REAL DEFAULT 0.5,
            assigned_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, skill_id)
    )""",

    "mt_employee_chat": """
        CREATE TABLE IF NOT EXISTS mt_employee_chat (
            chat_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            message TEXT NOT NULL,
            role TEXT DEFAULT 'assistant',
            context_json TEXT DEFAULT '{}',
            ai_model TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 题库 (与 mt_lang_qbank 独立，面向冰山中心跨学科) ──
    "mt_qbank_subject": """
        CREATE TABLE IF NOT EXISTS mt_qbank_subject (
            subject_id TEXT PRIMARY KEY,
            subject_name TEXT NOT NULL,
            category TEXT,
            difficulty TEXT DEFAULT 'medium',
            question_count INTEGER DEFAULT 0,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    "mt_qbank_knowledge_point": """
        CREATE TABLE IF NOT EXISTS mt_qbank_knowledge_point (
            kp_id TEXT PRIMARY KEY,
            subject_id TEXT,
            kp_name TEXT NOT NULL,
            description TEXT,
            parent_id TEXT,
            difficulty TEXT DEFAULT 'medium',
            question_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    "mt_qbank_questions": """
        CREATE TABLE IF NOT EXISTS mt_qbank_questions (
            question_id TEXT PRIMARY KEY,
            subject_id TEXT,
            kp_id TEXT,
            question_type TEXT DEFAULT 'choice',
            difficulty TEXT DEFAULT 'medium',
            question_text TEXT NOT NULL,
            options_json TEXT DEFAULT '[]',
            correct_answer TEXT,
            explanation TEXT,
            tags_json TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.6,
            usage_count INTEGER DEFAULT 0,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 成就/徽章 ────────────────────────────────────────────────
    "mt_iceberg_badge": """
        CREATE TABLE IF NOT EXISTS mt_iceberg_badge (
            badge_id TEXT PRIMARY KEY,
            badge_name TEXT NOT NULL,
            badge_category TEXT,
            icon_emoji TEXT DEFAULT '🏅',
            description TEXT,
            condition_json TEXT DEFAULT '{}',
            rarity REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    "mt_iceberg_achievement": """
        CREATE TABLE IF NOT EXISTS mt_iceberg_achievement (
            achievement_id TEXT PRIMARY KEY,
            badge_id TEXT NOT NULL,
            employee_id TEXT,
            center TEXT,
            context_json TEXT DEFAULT '{}',
            earned_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 技能使用日志 ────────────────────────────────────────────
    "mt_skill_usage_log": """
        CREATE TABLE IF NOT EXISTS mt_skill_usage_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id TEXT NOT NULL,
            user_id TEXT,
            employee_id TEXT,
            context TEXT,
            success INTEGER DEFAULT 1,
            duration_ms REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 语言学习 (DROP 空的 mt_lang_grammar 后重建) ────────────
    "mt_lang_session": """
        CREATE TABLE IF NOT EXISTS mt_lang_session (
            session_id TEXT PRIMARY KEY,
            employee_id TEXT,
            lang TEXT DEFAULT 'ja',
            session_type TEXT DEFAULT 'vocab',
            started_at TEXT DEFAULT (datetime('now','localtime')),
            ended_at TEXT,
            duration_ms REAL DEFAULT 0,
            score REAL DEFAULT 0,
            items_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0
    )""",

    "mt_lang_vocab_review": """
        CREATE TABLE IF NOT EXISTS mt_lang_vocab_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            word TEXT NOT NULL,
            reading TEXT,
            meaning TEXT,
            review_result TEXT,
            review_interval INTEGER DEFAULT 0,
            next_review TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # mt_lang_grammar 冲突处理: 原表 0 行 → DROP 后重建
}

# 需要 DROP 重建的空表
DROP_RECREATE_TABLES = ["mt_lang_grammar"]

# mt_lang_grammar 的新 DDL (覆盖旧的空表)
MT_LANG_GRAMMAR_DDL = """
    CREATE TABLE mt_lang_grammar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT,
        grammar_point TEXT NOT NULL,
        lang TEXT DEFAULT 'ja',
        practice_text TEXT,
        correct_answer TEXT,
        user_answer TEXT,
        result INTEGER DEFAULT 0,
        hint TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )"""


# ═══════════════════════════════════════════════════════════════════════
# Schema Seeder 主类
# ═══════════════════════════════════════════════════════════════════════

class IcebergSchemaSeeder:
    """🧊 冰山 Schema Seeder — 12 张表建表 + 智能 seed"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.stats: dict[str, int] = {}

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ─── 建表 ──────────────────────────────────────────────
    def create_all_tables(self) -> dict:
        """CREATE TABLE IF NOT EXISTS for all 12 schemas"""
        print("\n🧊 === Iceberg Schema Seeder: CREATE ALL TABLES ===\n")
        results = {}

        # 先 DROP 需要重建的空表
        for t in DROP_RECREATE_TABLES:
            try:
                cnt = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                if cnt == 0:
                    self.conn.execute(f"DROP TABLE IF EXISTS {t}")
                    print(f"  🔄 DROPped empty table → {t}")
                else:
                    print(f"  ⏭️ 保留非空表: {t} ({cnt} rows)")
            except Exception:
                pass

        for table_name, ddl in ICEBERG_SCHEMAS.items():
            try:
                self.conn.execute(ddl)
                self.conn.commit()
                # 验证
                cnt = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                status = "✅ EXISTS" if cnt >= 0 else "✅ CREATED"
                print(f"  {status} {table_name:30s} (rows={cnt})")
                results[table_name] = cnt
            except Exception as e:
                print(f"  ❌ {table_name}: {e}")
                results[table_name] = -1

        # 单独处理 mt_lang_grammar (DROP_RECREATE 已执行)
        try:
            self.conn.execute(MT_LANG_GRAMMAR_DDL)
            self.conn.commit()
            cnt = self.conn.execute("SELECT COUNT(*) FROM mt_lang_grammar").fetchone()[0]
            print(f"  ✅ CREATED mt_lang_grammar               (rows={cnt})")
            results["mt_lang_grammar"] = cnt
        except Exception as e:
            print(f"  ❌ mt_lang_grammar: {e}")

        # 创建索引提升查询性能
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_iae_role ON mt_ai_employees(role)",
            "CREATE INDEX IF NOT EXISTS idx_iae_center ON mt_ai_employees(center)",
            "CREATE INDEX IF NOT EXISTS idx_iae_status ON mt_ai_employees(status)",
            "CREATE INDEX IF NOT EXISTS idx_iaes_emp ON mt_ai_employee_skill(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_iaes_skill ON mt_ai_employee_skill(skill_id)",
            "CREATE INDEX IF NOT EXISTS idx_ec_emp ON mt_employee_chat(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_qbank_subject ON mt_qbank_questions(subject_id)",
            "CREATE INDEX IF NOT EXISTS idx_qbank_kp ON mt_qbank_questions(kp_id)",
            "CREATE INDEX IF NOT EXISTS idx_qbank_diff ON mt_qbank_questions(difficulty)",
            "CREATE INDEX IF NOT EXISTS idx_badge_category ON mt_iceberg_badge(badge_category)",
            "CREATE INDEX IF NOT EXISTS idx_ach_emp ON mt_iceberg_achievement(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_badge_center ON mt_iceberg_achievement(center)",
            "CREATE INDEX IF NOT EXISTS idx_usage_skill ON mt_skill_usage_log(skill_id)",
            "CREATE INDEX IF NOT EXISTS idx_usage_emp ON mt_skill_usage_log(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_usage_time ON mt_skill_usage_log(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_lang_session ON mt_lang_session(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_lang_vocab_session ON mt_lang_vocab_review(session_id)",
        ]
        for idx in indices:
            try:
                self.conn.execute(idx)
            except Exception:
                pass
        self.conn.commit()
        print(f"\n  📎 已创建 {len(indices)} 个索引\n")

        return results

    # ─── Seed: mt_ai_employees ────────────────────────────
    def seed_ai_employees(self) -> int:
        """从 mt_lab_hr_log + mtscos_ai_employees + ai_employees 衍生"""
        print("\n🤖 === Seed mt_ai_employees ===")

        # 1) 从 hr_log 提取活跃员工（有实际 action 记录）
        hr_emps = self.conn.execute("""
            SELECT employee_name, role, COUNT(*) as action_cnt
            FROM mt_lab_hr_log
            WHERE employee_name IS NOT NULL AND employee_name != ''
            GROUP BY employee_name
            ORDER BY action_cnt DESC
            LIMIT 50
        """).fetchall()

        # 2) 从 mtscos_ai_employees 导入 23 名
        mtscos_emps = self.conn.execute("""
            SELECT uid, name, role, dept, expertise_json, skills_json
            FROM mtscos_ai_employees WHERE is_active=1 OR status='active' OR status IS NULL
        """).fetchall()

        # 3) 从 ai_employees 导入
        ai_emps = self.conn.execute("""
            SELECT employee_code, name, status, capabilities, specialties FROM ai_employees
        """).fetchall()

        avatar_map = {
            "SEC": "🛡️", "security": "🛡️", "guardian": "🛡️", "cop": "🚔",
            "coder": "💻", "dev": "💻", "engineer": "⚙️", "ops": "🔧",
            "analyst": "📊", "finance": "💰", "trader": "📈", "medical": "⚕️",
            "edu": "📚", "teacher": "👩‍🏫", "writer": "✍️", "editor": "📝",
            "linguist": "🗣️", "artist": "🎨", "designer": "🎨",
            "daemon": "👹", "brain": "🧠", "skill": "⚡",
            "rule": "📏", "judge": "⚖️", "audit": "🔍",
            "assistant": "🤖", "assistant_default": "🤖",
        }

        def _avatar(role: str) -> str:
            rl = (role or "").lower()
            for kw, emoji in avatar_map.items():
                if kw in rl:
                    return emoji
            return "🤖"

        seeded = 0

        # Source A: mtscos_ai_employees (优先级最高)
        for uid, name, role, dept, expertise, skills in mtscos_emps:
            emp_id = f"emp_mtscos_{uid}"
            try:
                self.conn.execute("SELECT 1 FROM mt_ai_employees WHERE employee_id=?", (emp_id,))
                if self.conn.fetchone():
                    continue
                self.conn.execute("""
                    INSERT INTO mt_ai_employees (employee_id, name, role, center, status, level,
                                                 scores_json, skills_json, avatar_emoji, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (emp_id, name or uid, role or "assistant", dept, "active", 1.5,
                      "{}", skills or "[]", _avatar(role), "mtscos_ai_employees"))
                seeded += 1
            except Exception as e:
                print(f"    ⚠️ mtscos emp {uid}: {e}")

        # Source B: ai_employees
        for code, name, status, caps, specs in ai_emps:
            emp_id = f"emp_ai_{code or name}"
            try:
                self.conn.execute("SELECT 1 FROM mt_ai_employees WHERE employee_id=?", (emp_id,))
                if self.conn.fetchone():
                    continue
                role = "assistant"
                if specs:
                    try:
                        s = json.loads(specs) if isinstance(specs, str) else specs
                        if isinstance(s, list) and s:
                            role = str(s[0]) if s else "assistant"
                    except Exception:
                        role = str(specs)[:20] if specs else "assistant"
                center = None
                self.conn.execute("""
                    INSERT INTO mt_ai_employees (employee_id, name, role, center, status, level,
                                                 scores_json, skills_json, avatar_emoji, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (emp_id, name or code, role, center, status or "active", 1.2,
                      "{}", caps or "[]", _avatar(role), "ai_employees"))
                seeded += 1
            except Exception as e:
                print(f"    ⚠️ ai_emp {code}: {e}")

        # Source C: hr_log 活跃员工 (去重, 跳过已存在的)
        existing_names = {r[1] for r in self.conn.execute(
            "SELECT employee_id, name FROM mt_ai_employees").fetchall()}
        for emp_name, role, act_cnt in hr_emps:
            if emp_name in existing_names:
                continue
            emp_id = f"emp_hr_{emp_name}"
            # 根据 action 频率推断 level
            level = min(5.0, 1.0 + act_cnt / 500)
            center = None
            self.conn.execute("""
                INSERT OR IGNORE INTO mt_ai_employees (employee_id, name, role, center, status, level,
                                                       scores_json, skills_json, avatar_emoji, source)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (emp_id, emp_name, role or "employee", center, "active", round(level, 2),
                  "{}", "[]", _avatar(role or ""), "mt_lab_hr_log"))
            seeded += 1
            existing_names.add(emp_name)

        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0]
        print(f"  ✅ Seeded {seeded} new AI employees (total now: {total})")
        self.stats["mt_ai_employees"] = total
        return seeded

    # ─── Seed: mt_ai_employee_skill ──────────────────────
    def seed_employee_skill(self) -> int:
        """每个员工分配 3-5 个技能 (从 mt_skill_registry 衍生, 基于 role 关键词匹配)"""
        print("\n🔗 === Seed mt_ai_employee_skill ===")

        employees = self.conn.execute(
            "SELECT employee_id, name, role FROM mt_ai_employees WHERE source!='ai_employees' LIMIT 30"
        ).fetchall()

        # 获取所有可用技能
        skills = self.conn.execute(
            "SELECT skill_id, skill_name, category, trigger_keywords FROM mt_skill_registry WHERE readiness=1"
        ).fetchall()

        # 预计算 role → skill_category 映射
        role_cat_map = {
            "employee": ["daemon", "ai_network", "prompt framework"],
            "SEC_QA": ["daemon", "ai_network"],
            "arduino_detect": ["daemon"],
            "arduino_tutor": ["daemon", "prompt template"],
            "auto_repair": ["daemon", "prompt framework"],
            "copy_chapter_planner": ["prompt template", "prompt framewor"],
            "copy_chapter_writer": ["prompt template", "prompt tip"],
            "copy_consistency_checker": ["daemon", "prompt tip"],
            "copy_copyright_auditor": ["daemon"],
            "copy_inspector": ["daemon", "prompt tip"],
            "copy_outline_writer": ["prompt template", "prompt framewor"],
            "copy_polisher": ["prompt tip", "prompt template"],
            "copy_rag_keeper": ["ai_network", "brain feed"],
            "deep_inspector": ["daemon", "prompt tip"],
            "edu_sync_adult": ["prompt template", "prompt framework"],
            "edu_sync_high": ["prompt template", "prompt framework"],
            "edu_sync_k12": ["prompt template", "prompt framework"],
            "network_maintainer": ["daemon", "ai_network"],
            "patrol_inspector": ["daemon"],
            "smart_mount": ["daemon"],
        }

        seeded = 0
        for emp_id, emp_name, emp_role in employees:
            # 找到匹配的技能类别
            cats = role_cat_map.get(emp_role, ["daemon", "prompt template"])
            matched_skills = []
            for skill_id, skill_name, cat, keywords in skills:
                if any(c in (cat or "") for c in cats):
                    matched_skills.append(skill_id)
            # 随机补足 3 个
            import random
            random.seed(hash(emp_id) % 2**31)
            while len(matched_skills) < 3 and len(skills) > 0:
                pick = random.choice(skills)[0]
                if pick not in matched_skills:
                    matched_skills.append(pick)
            matched_skills = matched_skills[:5]  # 每个员工最多 5 技能

            for sk in matched_skills:
                try:
                    self.conn.execute("""
                        INSERT OR IGNORE INTO mt_ai_employee_skill 
                        (employee_id, skill_id, proficiency)
                        VALUES (?,?,?)
                    """, (emp_id, sk, round(random.uniform(0.4, 0.9), 2)))
                    seeded += 1
                except Exception:
                    pass

        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM mt_ai_employee_skill").fetchone()[0]
        print(f"  ✅ Seeded {seeded} emp-skill links (total: {total})")
        self.stats["mt_ai_employee_skill"] = total
        return seeded

    # ─── Seed: 题库三表 ───────────────────────────────────
    def seed_qbank(self) -> dict:
        """从 mt_iceberg_content_matrix 的 domain 衍生学科, 从 content_key 衍生知识点"""
        print("\n📚 === Seed QBank (subject + kp + questions) ===")
        result = {"subject": 0, "kp": 0, "questions": 0}

        # ── Subjects (从 content_matrix domain 衍生) ──
        domains = self.conn.execute(
            "SELECT DISTINCT domain FROM mt_iceberg_content_matrix WHERE domain IS NOT NULL AND domain!=''"
        ).fetchall()

        subject_meta = {
            "gobelin": ("古灵阁金融沙盘", "finance", "hard", "证券交易模拟沙盘，涵盖股票/基金/期权等金融衍生品"),
            "AI UI设计系统": ("AI UI设计系统", "design", "medium", "基于 Awwwards 2025 趋势的组件化设计规范"),
            "AI提示词框架": ("AI 提示词工程", "engineering", "medium", "Prompt 7 大框架 + 反模式 + 链式思维"),
            "AI视频公式库": ("AI 视频公式库", "media", "medium", "AI 视频生成公式 + 叙事结构 + 节奏控制"),
            "Coze自动化工作流": ("Coze 工作流", "automation", "easy", "Coze 工作流编排 + 插件 + Bot 发布"),
            "Prompt7大技巧": ("Prompt 7 大技巧", "engineering", "easy", "LLM 高效交互的 7 类技巧"),
            "去AI味指南": ("去 AI 味指南", "writing", "medium", "降低 AI 感的文风改写技术"),
            "多模态Prompt": ("多模态 Prompt", "multimodal", "medium", "图像/音频/视频 Prompt 工程"),
        }

        for (domain,) in domains:
            meta = subject_meta.get(domain, (domain, "general", "medium", f"{domain} 相关知识体系"))
            sid = f"subj_{domain.replace(' ', '_').replace('/', '_')[:24]}"
            try:
                self.conn.execute("""
                    INSERT OR IGNORE INTO mt_qbank_subject 
                    (subject_id, subject_name, category, difficulty, description, question_count)
                    VALUES (?,?,?,?,?,0)
                """, (sid, meta[0], meta[1], meta[2], meta[3]))
                result["subject"] += 1
            except Exception as e:
                print(f"    ⚠️ subject {domain}: {e}")

        self.conn.commit()

        # ── Knowledge Points (从 content_key 前缀衍生) ──
        content_keys = self.conn.execute(
            "SELECT DISTINCT content_key FROM mt_iceberg_content_matrix LIMIT 50"
        ).fetchall()

        for (ckey,) in content_keys:
            if not ckey or '.' not in ckey:
                continue
            parts = ckey.split('.')
            # 从 content_key 的首段找 subject
            subj_match = self.conn.execute(
                "SELECT subject_id FROM mt_qbank_subject WHERE subject_name LIKE ?", (f"%{parts[0]}%",)
            ).fetchone()
            if not subj_match:
                continue
            sid = subj_match[0]
            kp_name = parts[-1] if len(parts) > 1 else ckey
            kpid = f"kp_{sid}_{kp_name}"[:64]
            try:
                self.conn.execute("""
                    INSERT OR IGNORE INTO mt_qbank_knowledge_point
                    (kp_id, subject_id, kp_name, description, parent_id, difficulty)
                    VALUES (?,?,?,?,?,?)
                """, (kpid, sid, kp_name, f"{ckey} 相关知识点", None, "medium"))
                result["kp"] += 1
            except Exception:
                pass

        self.conn.commit()

        # ── Questions (从 content_matrix 的 text 字段衍生) ──
        contents = self.conn.execute(
            "SELECT content_key, text, domain, lang, priority FROM mt_iceberg_content_matrix LIMIT 200"
        ).fetchall()

        import random
        random.seed(42)
        q_types = ["choice", "judge", "essay", "choice", "choice"]  # 选择占多数

        for idx, (ckey, text, domain, lang, priority) in enumerate(contents):
            if not text or len(text) < 10:
                continue
            # 找 subject
            sid_row = self.conn.execute(
                "SELECT subject_id FROM mt_qbank_subject WHERE subject_name LIKE ? OR subject_id LIKE ?",
                (f"%{domain}%", f"%{domain}%")
            ).fetchone()
            if not sid_row:
                continue
            sid = sid_row[0]

            qid = f"q_{sid}_{idx}_{uuid.uuid4().hex[:6]}"
            qtype = random.choice(q_types)

            # 从 text 生成题目
            question_text = f"关于「{ckey}」，以下说法正确的是？"
            if qtype == "judge":
                question_text = f"判断: {text[:80]}... — 这个说法是否正确？"
                options = json.dumps(["正确", "错误"], ensure_ascii=False)
                answer = random.choice(["正确", "错误"])
            elif qtype == "essay":
                question_text = f"请解释「{ckey}」的核心概念。"
                options = json.dumps([], ensure_ascii=False)
                answer = text[:200]
            else:
                question_text = f"「{ckey}」的主要内容是什么？"
                distractors = [
                    f"完全不相关的概念 A",
                    f"部分相关但不准确的概念 B",
                    f"混淆概念 C",
                ]
                options = json.dumps([text[:60]] + distractors, ensure_ascii=False)
                answer = text[:60]

            difficulty = "hard" if (priority or 100) >= 90 else "easy" if (priority or 100) <= 30 else "medium"

            try:
                self.conn.execute("""
                    INSERT OR IGNORE INTO mt_qbank_questions
                    (question_id, subject_id, kp_id, question_type, difficulty,
                     question_text, options_json, correct_answer, explanation,
                     tags_json, confidence, usage_count, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (qid, sid, None, qtype, difficulty, question_text, options,
                      answer, f"基于冰山矩阵 content_key={ckey}, lang={lang}",
                      json.dumps([domain, lang or ""], ensure_ascii=False),
                      round(0.5 + random.random() * 0.4, 2), 0, "iceberg_content_matrix"))
                result["questions"] += 1
            except Exception as e:
                print(f"    ⚠️ q {qid[:30]}: {e}")

        # 更新 subject 的 question_count
        self.conn.execute("""
            UPDATE mt_qbank_subject SET question_count = (
                SELECT COUNT(*) FROM mt_qbank_questions WHERE mt_qbank_questions.subject_id = mt_qbank_subject.subject_id
            )
        """)
        self.conn.execute("""
            UPDATE mt_qbank_knowledge_point SET question_count = (
                SELECT COUNT(*) FROM mt_qbank_questions WHERE mt_qbank_questions.kp_id = mt_qbank_knowledge_point.kp_id
            )
        """)
        self.conn.commit()

        print(f"  ✅ Subjects: {result['subject']}, KPs: {result['kp']}, Questions: {result['questions']}")
        self.stats.update({f"mt_qbank_{k}": v for k, v in result.items()})
        return result

    # ─── Seed: 冰山徽章 (预设 20+ 个) ────────────────────
    def seed_badges(self) -> int:
        """预设徽章 (不依赖 Ollama, 快速稳定)"""
        print("\n🏅 === Seed mt_iceberg_badge ===")

        badges = [
            # ── 技能掌握徽章 ──
            ("badge_skill_master", "技能大师", "skill", "⚡", "在某技能上达到精通级别（50+ 次调用, 成功率>90%）",
             json.dumps({"type": "skill_mastery", "threshold": 50}, ensure_ascii=False), 0.3),
            ("badge_skill_apprentice", "技能学徒", "skill", "🌱", "首次成功调用某技能",
             json.dumps({"type": "skill_first_use"}, ensure_ascii=False), 0.9),
            ("badge_switch_jockey", "Switch 骑手", "skill", "🎛️", "一周内切换 20+ 次开关",
             json.dumps({"type": "switch_count", "threshold": 20}, ensure_ascii=False), 0.2),

            # ── 成就徽章 ──
            ("badge_first_employee", "初代员工", "achievement", "🎖️", "最早上线的前 5 名 AI 员工",
             json.dumps({"type": "early_join", "rank": 5}, ensure_ascii=False), 0.1),
            ("badge_veteran", "老兵", "achievement", "🎗️", "累计执行 1000+ 次 hall 任务",
             json.dumps({"type": "hall_tasks", "threshold": 1000}, ensure_ascii=False), 0.4),
            ("badge_workaholic", "工作狂", "achievement", "💼", "单日执行 100+ 次 action",
             json.dumps({"type": "daily_actions", "threshold": 100}, ensure_ascii=False), 0.3),
            ("badge_iceberg_pioneer", "冰山先驱", "achievement", "🧊", "参与冰山矩阵首批 687 条内容构建",
             json.dumps({"type": "iceberg_seed"}, ensure_ascii=False), 0.5),

            # ── 学科徽章 ──
            ("badge_finance_pro", "金融专家", "course", "💰", "古灵阁沙盘交易胜率>70%",
             json.dumps({"type": "finance_winrate", "threshold": 0.7}, ensure_ascii=False), 0.4),
            ("badge_lang_jlpt_n2", "日语 N2", "course", "🗾", "日语语法练习正确率稳定 N2 水平",
             json.dumps({"type": "lang_jlpt", "level": "N2"}, ensure_ascii=False), 0.3),
            ("badge_lang_cefr_b2", "英语 B2", "course", "🌍", "英语 CEFR B2 水平达成",
             json.dumps({"type": "lang_cefr", "level": "B2"}, ensure_ascii=False), 0.3),
            ("badge_prompt_pro", "提示词专家", "course", "💡", "Prompt 7 大框架全部掌握",
             json.dumps({"type": "prompt_mastery", "count": 7}, ensure_ascii=False), 0.5),

            # ── 特殊徽章 ──
            ("badge_daemon_whisperer", "守护灵沟通者", "special", "👹", "让 daemon 守护零异常运行 7 天",
             json.dumps({"type": "daemon_uptime", "days": 7}, ensure_ascii=False), 0.1),
            ("badge_guardian", "铁壁守护", "special", "🛡️", "零漏洞漏过 (100+ 次巡检全部 PASS)",
             json.dumps({"type": "security_perfect", "threshold": 100}, ensure_ascii=False), 0.1),
            ("badge_crisis_handler", "危机处理者", "special", "🚨", "成功处理 10+ 次 HEAL_ 事件",
             json.dumps({"type": "heal_events", "threshold": 10}, ensure_ascii=False), 0.2),
            ("badge_autopilot", "自动驾驶员", "special", "🚗", "Andromeda 自动驾驶 72h 无人工干预",
             json.dumps({"type": "autopilot_hours", "threshold": 72}, ensure_ascii=False), 0.05),

            # ── 协作徽章 ──
            ("badge_collab_star", "协作之星", "achievement", "⭐", "与 5+ 不同中心员工协作完成任务",
             json.dumps({"type": "cross_center_collab", "count": 5}, ensure_ascii=False), 0.3),
            ("badge_mentor", "良师益友", "achievement", "🎓", "成功指导 10+ 次其他员工升级",
             json.dumps({"type": "mentee_upgrade", "count": 10}, ensure_ascii=False), 0.2),
            ("badge_hall_legend", "任务厅传奇", "achievement", "🏆", "hall_task 完成数进入 TOP 10%",
             json.dumps({"type": "hall_task_top", "percentile": 10}, ensure_ascii=False), 0.2),
        ]

        seeded = 0
        for bid, bname, cat, icon, desc, cond, rarity in badges:
            try:
                self.conn.execute("""
                    INSERT OR IGNORE INTO mt_iceberg_badge
                    (badge_id, badge_name, badge_category, icon_emoji, description, condition_json, rarity)
                    VALUES (?,?,?,?,?,?,?)
                """, (bid, bname, cat, icon, desc, cond, rarity))
                seeded += 1
            except Exception as e:
                print(f"    ⚠️ badge {bid}: {e}")

        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM mt_iceberg_badge").fetchone()[0]
        print(f"  ✅ Seeded {seeded} badges (total: {total})")
        self.stats["mt_iceberg_badge"] = total
        return seeded

    # ─── Seed: 成就记录 ──────────────────────────────────
    def seed_achievements(self) -> int:
        """为前 10 名活跃员工颁发初始徽章 (初代员工 + 工作狂)"""
        print("\n🎖️ === Seed mt_iceberg_achievement ===")

        top_emps = self.conn.execute("""
            SELECT employee_id, name FROM mt_ai_employees ORDER BY rowid ASC LIMIT 10
        """).fetchall()

        badges = self.conn.execute("SELECT badge_id, badge_category FROM mt_iceberg_badge").fetchall()

        seeded = 0
        for emp_id, name in top_emps:
            # 给前 3 名发"初代员工"
            row = self.conn.execute("SELECT COUNT(*) FROM mt_iceberg_achievement WHERE employee_id=?",
                                    (emp_id,)).fetchone()[0]
            if row == 0:
                # 发一个初始徽章
                early_badge = next((b for b in badges if b[0] == "badge_first_employee"), None)
                if early_badge:
                    aid = f"ach_{emp_id}_{early_badge[0]}"
                    try:
                        self.conn.execute("""
                            INSERT OR IGNORE INTO mt_iceberg_achievement
                            (achievement_id, badge_id, employee_id, context_json)
                            VALUES (?,?,?,?)
                        """, (aid, early_badge[0], emp_id,
                              json.dumps({"reason": "初代员工自动授予", "auto_seed": True}, ensure_ascii=False)))
                        seeded += 1
                    except Exception:
                        pass

                # 给一些员工发"技能学徒"
                apprentice = next((b for b in badges if b[0] == "badge_skill_apprentice"), None)
                if apprentice:
                    aid2 = f"ach_{emp_id}_{apprentice[0]}"
                    try:
                        self.conn.execute("""
                            INSERT OR IGNORE INTO mt_iceberg_achievement
                            (achievement_id, badge_id, employee_id, context_json)
                            VALUES (?,?,?,?)
                        """, (aid2, apprentice[0], emp_id,
                              json.dumps({"reason": "初始技能学徒授予", "auto_seed": True}, ensure_ascii=False)))
                        seeded += 1
                    except Exception:
                        pass

        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM mt_iceberg_achievement").fetchone()[0]
        print(f"  ✅ Seeded {seeded} achievements (total: {total})")
        self.stats["mt_iceberg_achievement"] = total
        return seeded

    # ─── Seed: 技能使用日志 ──────────────────────────────
    def seed_skill_usage_log(self) -> int:
        """从 mt_center_evolution_log (62663 rows) 和 mt_skill_registry 衍生"""
        print("\n⚙️ === Seed mt_skill_usage_log ===")

        # 方案: 从 evolution_log 的各类事件衍生 (因为没有 SKILL_USED)
        events = self.conn.execute("""
            SELECT center_name, event, detail, created_at 
            FROM mt_center_evolution_log 
            ORDER BY created_at DESC 
            LIMIT 500
        """).fetchall()

        # center_name → 可能使用的 skill_id
        center_skills = self.conn.execute(
            "SELECT skill_id, skill_name, source_daemon FROM mt_skill_registry WHERE readiness=1"
        ).fetchall()

        seeded = 0
        for center, event, detail, ts in events:
            if not center:
                continue
            # 找匹配的 skill
            skill_id = None
            for sid, sname, sdaemon in center_skills:
                if sdaemon and (sdaemon in center or center in sdaemon or center[:3] in sdaemon):
                    skill_id = sid
                    break
            if not skill_id:
                # 随机选一个 daemon 技能
                daemon_skills = [s for s in center_skills if s[2] == "daemon"]
                if daemon_skills:
                    import random
                    skill_id = random.choice(daemon_skills)[0]
            if not skill_id:
                continue

            # 选一个活跃员工
            emp = self.conn.execute(
                "SELECT employee_id FROM mt_ai_employees ORDER BY rowid ASC LIMIT 1"
            ).fetchone()
            emp_id = emp[0] if emp else None

            try:
                self.conn.execute("""
                    INSERT INTO mt_skill_usage_log
                    (skill_id, user_id, employee_id, context, success, duration_ms, created_at)
                    VALUES (?,?,?,?,?,?,?)
                """, (skill_id, None, emp_id,
                      f"center={center}, event={event}, detail={detail[:80]}",
                      1 if "ALERT" not in (event or "") else 0,
                      round(__import__("random").uniform(100, 5000), 0),
                      ts))
                seeded += 1
            except Exception:
                pass

        self.conn.commit()
        total = self.conn.execute("SELECT COUNT(*) FROM mt_skill_usage_log").fetchone()[0]
        print(f"  ✅ Seeded {seeded} skill usage logs (total: {total})")
        self.stats["mt_skill_usage_log"] = total
        return seeded

    # ─── Seed: 语言学习三表 ──────────────────────────────
    def seed_lang_tables(self) -> dict:
        """生成示例语言学习会话、词汇复习、语法练习"""
        print("\n🗣️ === Seed mt_lang_session / vocab_review / grammar ===")
        result = {"session": 0, "vocab": 0, "grammar": 0}

        import random
        random.seed(99)

        langs = ["ja", "en", "ko"]
        session_types = ["vocab", "grammar", "listening", "speaking"]
        vocab_data = {
            "ja": [
                ("日本", "にほん", "日本"), ("水", "みず", "水"), ("火", "ひ", "火"),
                ("山", "やま", "山"), ("川", "かわ", "河"), ("空", "そら", "天空"),
                ("友達", "ともだち", "朋友"), ("学校", "がっこう", "学校"),
            ],
            "en": [
                ("hello", "", "你好"), ("world", "", "世界"), ("programming", "", "编程"),
                ("artificial", "", "人工的"), ("intelligence", "", "智能"),
                ("language", "", "语言"), ("learning", "", "学习"),
            ],
            "ko": [
                ("안녕하세요", "", "你好"), ("사랑", "", "爱"), ("학교", "", "学校"),
                ("친구", "", "朋友"), ("물", "", "水"),
            ],
        }

        # 员工
        emps = self.conn.execute("SELECT employee_id FROM mt_ai_employees LIMIT 3").fetchall()

        sessions_seeded = 0
        for lang in langs:
            for stype in session_types[:3]:
                for emp in (emps or [("emp_hr_自动修复工程师",)]):
                    emp_id = emp[0]
                    sid = f"sess_{uuid.uuid4().hex[:12]}"
                    duration = random.randint(120, 1800) * 1000
                    items = random.randint(5, 20)
                    correct = int(items * random.uniform(0.5, 0.95))
                    score = round(correct / items * 100, 1) if items > 0 else 0
                    try:
                        self.conn.execute("""
                            INSERT OR IGNORE INTO mt_lang_session
                            (session_id, employee_id, lang, session_type, duration_ms,
                             score, items_count, correct_count, started_at, ended_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)
                        """, (sid, emp_id, lang, stype, duration, score, items, correct,
                              datetime.now().isoformat(), datetime.now().isoformat()))
                        sessions_seeded += 1

                        # 生成词汇复习记录
                        words = vocab_data.get(lang, [])
                        if stype == "vocab" and words:
                            for w, rd, mn in words[:items]:
                                res = random.choice(["correct", "wrong", "hard", "correct", "correct"])
                                interval = {"correct": 1, "wrong": 0, "hard": 1}[res] * random.randint(1, 7)
                                try:
                                    self.conn.execute("""
                                        INSERT INTO mt_lang_vocab_review
                                        (session_id, word, reading, meaning, review_result, review_interval, next_review)
                                        VALUES (?,?,?,?,?,?,?)
                                    """, (sid, w, rd, mn, res, interval,
                                          datetime.now().isoformat()))
                                    result["vocab"] += 1
                                except Exception:
                                    pass

                        # 生成语法练习
                        if stype == "grammar":
                            for i in range(max(3, correct)):
                                gp = f"{lang} Grammar Point {i+1}"
                                text = f"Choose the correct form for: {gp}"
                                ha = random.choice([True, False, True, True])
                                try:
                                    self.conn.execute("""
                                        INSERT INTO mt_lang_grammar
                                        (employee_id, grammar_point, lang, practice_text,
                                         correct_answer, user_answer, result, hint)
                                        VALUES (?,?,?,?,?,?,?,?)
                                    """, (emp_id, gp, lang, text,
                                          "answer_A" if ha else "answer_B",
                                          "answer_A" if ha else "answer_A",
                                          1 if ha else 0,
                                          "Consider tense consistency"))
                                    result["grammar"] += 1
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"    ⚠️ lang session: {e}")

        self.conn.commit()
        result["session"] = sessions_seeded
        print(f"  ✅ Sessions: {sessions_seeded}, VocabReviews: {result['vocab']}, Grammar: {result['grammar']}")
        self.stats.update({f"mt_lang_{k}": v for k, v in result.items()})
        return result

    # ─── 一键全量 seed ────────────────────────────────────
    def run_full_seed(self) -> dict:
        print("🧊" * 40)
        print("🧊  ICEBERG SCHEMA SEEDER — FULL SEED")
        print("🧊" * 40)

        self.seed_ai_employees()
        self.seed_employee_skill()
        self.seed_qbank()
        self.seed_badges()
        self.seed_achievements()
        self.seed_skill_usage_log()
        self.seed_lang_tables()

        print("\n" + "=" * 55)
        print("🧊  SEED SUMMARY")
        print("=" * 55)
        for table_name, cnt in sorted(self.stats.items()):
            icon = "🔵" if cnt > 0 else "⚪"
            print(f"  {icon} {table_name:35s}: {cnt:>6} rows")
        print()
        return self.stats

    # ─── 验证 ─────────────────────────────────────────────
    def verify_all(self) -> dict:
        print("\n🧊 === ICEBERG VERIFICATION ===")
        tables_to_check = list(ICEBERG_SCHEMAS.keys()) + ["mt_lang_grammar"]
        results = {}
        all_ok = True
        for t in tables_to_check:
            try:
                cols = self.conn.execute(f"PRAGMA table_info({t})").fetchall()
                cnt = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                icon = "✅" if cnt > 0 else "⚠️ (empty)"
                print(f"  {icon} {t:35s}: {cnt:>6} rows  ({len(cols)} cols)")
                results[t] = cnt
                if cnt == 0 and t not in ("mt_employee_chat", "mt_lang_session"):
                    all_ok = False
            except Exception as e:
                print(f"  ❌ {t}: {str(e)[:60]}")
                results[t] = -1
                all_ok = False

        print(f"\n{'🎉 All 12 tables fully seeded!' if all_ok else '⚠️ Some tables are empty'}")
        return results


# ═══════════════════════════════════════════════════════════════════════
# Server 启动阶段调用的集成入口 (接受外部 conn, 由 server_real_db.py 调用)
# ═══════════════════════════════════════════════════════════════════════

def ensure_iceberg_tables_on_conn(conn, run_seed: bool = True) -> dict:
    """
    给一个已有的 sqlite3 connection, 确保 12 张冰山表都存在 + 可选 seed。
    幂等: 表存在就跳过, 有数据就不再 seed。

    用法 (server_real_db.py 的迁移区块):
        from engines.iceberg_schema_seeder import ensure_iceberg_tables_on_conn
        ensure_iceberg_tables_on_conn(conn)
    """
    import random as _r
    _r.seed(42)

    results = {}

    # 1) DROP 重建空表
    for t in DROP_RECREATE_TABLES:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if cnt == 0:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
        except Exception:
            pass

    # 2) CREATE ALL
    for table_name, ddl in ICEBERG_SCHEMAS.items():
        try:
            conn.execute(ddl)
            conn.commit()
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            results[table_name] = cnt
        except Exception:
            results[table_name] = -1
    # mt_lang_grammar
    try:
        conn.execute(MT_LANG_GRAMMAR_DDL)
        conn.commit()
        results["mt_lang_grammar"] = conn.execute("SELECT COUNT(*) FROM mt_lang_grammar").fetchone()[0]
    except Exception:
        pass

    # 3) 索引
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_iae_role ON mt_ai_employees(role)",
        "CREATE INDEX IF NOT EXISTS idx_iae_center ON mt_ai_employees(center)",
        "CREATE INDEX IF NOT EXISTS idx_iae_status ON mt_ai_employees(status)",
        "CREATE INDEX IF NOT EXISTS idx_qbank_subject ON mt_qbank_questions(subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_qbank_diff ON mt_qbank_questions(difficulty)",
        "CREATE INDEX IF NOT EXISTS idx_badge_category ON mt_iceberg_badge(badge_category)",
        "CREATE INDEX IF NOT EXISTS idx_ach_emp ON mt_iceberg_achievement(employee_id)",
        "CREATE INDEX IF NOT EXISTS idx_usage_skill ON mt_skill_usage_log(skill_id)",
        "CREATE INDEX IF NOT EXISTS idx_usage_time ON mt_skill_usage_log(created_at)",
    ]
    for idx in indices:
        try:
            conn.execute(idx)
        except Exception:
            pass
    conn.commit()

    # ── Seed (只在空表时) ──
    if run_seed:
        _seed_all_on_conn(conn)

    return results


def _seed_all_on_conn(conn):
    """内联 seed — 完全独立不依赖 IcebergSchemaSeeder 类"""
    import random as _r
    _r.seed(42)

    print("\n🧊 [ICEBERG] Seeding 12 iceberg tables...")

    # ── mt_ai_employees ──
    existing_emps = conn.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0]
    if existing_emps == 0:
        # Source A: mtscos_ai_employees (23 rows)
        mtscos_emps = conn.execute("""
            SELECT uid, name, role, dept, skills_json
            FROM mtscos_ai_employees WHERE is_active=1 OR status='active' OR status IS NULL
        """).fetchall()

        # Source B: ai_employees (45 rows)
        ai_emps = conn.execute("SELECT employee_code, name, status FROM ai_employees").fetchall()

        # Source C: hr_log 活跃员工
        hr_emps = conn.execute("""
            SELECT employee_name, role, COUNT(*) cnt FROM mt_lab_hr_log
            WHERE employee_name IS NOT NULL AND employee_name!=''
            GROUP BY employee_name ORDER BY cnt DESC LIMIT 50
        """).fetchall()

        avatar_map = {
            "SEC": "🛡️", "coder": "💻", "engineer": "⚙️", "analyst": "📊",
            "finance": "💰", "trader": "📈", "edu": "📚", "teacher": "👩‍🏫",
            "assistant": "🤖", "employee": "🤖", "rule": "📏", "audit": "🔍",
            "writer": "✍️", "daemon": "👹", "brain": "🧠", "linguist": "🗣️",
        }
        def _av(role):
            rl = (role or "").lower()
            for k, v in avatar_map.items():
                if k in rl: return v
            return "🤖"

        seeded = 0
        for uid, name, role, dept, skills in mtscos_emps:
            eid = f"emp_mtscos_{uid}"
            try:
                conn.execute("INSERT OR IGNORE INTO mt_ai_employees (employee_id,name,role,center,status,level,scores_json,skills_json,avatar_emoji,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (eid, name or uid, role or "assistant", dept, "active", 1.5, "{}", skills or "[]", _av(role), "mtscos"))
                seeded += 1
            except Exception: pass

        for code, name, status in ai_emps:
            eid = f"emp_ai_{code or name}"
            try:
                conn.execute("INSERT OR IGNORE INTO mt_ai_employees (employee_id,name,role,status,level,scores_json,skills_json,avatar_emoji,source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (eid, name or code, "assistant", status or "active", 1.2, "{}", "[]", "🤖", "ai_employees"))
                seeded += 1
            except Exception: pass

        existing_names = {r[0] for r in conn.execute("SELECT name FROM mt_ai_employees").fetchall()}
        for ename, erole, act_cnt in hr_emps:
            if ename in existing_names: continue
            eid = f"emp_hr_{ename}"
            level = min(5.0, 1.0 + act_cnt / 500)
            try:
                conn.execute("INSERT OR IGNORE INTO mt_ai_employees (employee_id,name,role,status,level,scores_json,skills_json,avatar_emoji,source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (eid, ename, erole or "employee", "active", round(level,2), "{}", "[]", _av(erole or ""), "hr_log"))
                seeded += 1
            except Exception: pass

        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0]
        print(f"  🤖 AI employees: {seeded} new (total {total})")
    else:
        print(f"  🤖 AI employees already seeded ({existing_emps})")

    # ── mt_ai_employee_skill ──
    existing_links = conn.execute("SELECT COUNT(*) FROM mt_ai_employee_skill").fetchone()[0]
    if existing_links == 0:
        emps = conn.execute("SELECT employee_id FROM mt_ai_employees LIMIT 30").fetchall()
        skills = conn.execute("SELECT skill_id FROM mt_skill_registry WHERE readiness=1 LIMIT 50").fetchall()
        for (eid,) in emps:
            pick = _r.sample([s[0] for s in skills], min(3, len(skills)))
            for sk in pick:
                try:
                    conn.execute("INSERT OR IGNORE INTO mt_ai_employee_skill (employee_id,skill_id,proficiency) VALUES (?,?,?)",
                        (eid, sk, round(_r.uniform(0.4,0.9), 2)))
                except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_ai_employee_skill").fetchone()[0]
        print(f"  🔗 emp-skill links: {total}")

    # ── mt_qbank_subject ──
    subj_cnt = conn.execute("SELECT COUNT(*) FROM mt_qbank_subject").fetchone()[0]
    if subj_cnt == 0:
        domains = conn.execute("SELECT DISTINCT domain FROM mt_iceberg_content_matrix WHERE domain IS NOT NULL AND domain!=''").fetchall()
        subject_meta = {
            "gobelin": ("古灵阁金融沙盘", "finance", "hard", "证券交易模拟沙盘"),
            "AI UI设计系统": ("AI UI设计系统", "design", "medium", "组件化设计规范"),
            "AI提示词框架": ("AI 提示词工程", "engineering", "medium", "Prompt 框架 + 反模式"),
            "AI视频公式库": ("AI 视频公式库", "media", "medium", "AI 视频生成公式"),
            "Coze自动化工作流": ("Coze 工作流", "automation", "easy", "Coze 工作流编排"),
            "Prompt7大技巧": ("Prompt 7 大技巧", "engineering", "easy", "LLM 高效交互"),
            "去AI味指南": ("去 AI 味指南", "writing", "medium", "降低 AI 感的文风改写"),
            "多模态Prompt": ("多模态 Prompt", "multimodal", "medium", "图像/音频/视频 Prompt"),
        }
        for (domain,) in domains:
            meta = subject_meta.get(domain, (domain, "general", "medium", f"{domain} 知识体系"))
            sid = f"subj_{domain[:20].replace(' ','_').replace('/','_')}"
            try:
                conn.execute("INSERT OR IGNORE INTO mt_qbank_subject (subject_id,subject_name,category,difficulty,description,question_count) VALUES (?,?,?,?,?,0)",
                    (sid, meta[0], meta[1], meta[2], meta[3]))
            except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_qbank_subject").fetchone()[0]
        print(f"  📚 Subjects: {total}")

    # ── mt_qbank_knowledge_point ──
    kp_cnt = conn.execute("SELECT COUNT(*) FROM mt_qbank_knowledge_point").fetchone()[0]
    if kp_cnt == 0:
        content_keys = conn.execute("SELECT DISTINCT content_key FROM mt_iceberg_content_matrix LIMIT 50").fetchall()
        for (ckey,) in content_keys:
            if not ckey or '.' not in ckey: continue
            parts = ckey.split('.')
            subj_row = conn.execute("SELECT subject_id FROM mt_qbank_subject WHERE subject_name LIKE ?", (f"%{parts[0]}%",)).fetchone()
            if not subj_row: continue
            sid = subj_row[0]
            kp_name = parts[-1]
            kpid = f"kp_{sid}_{kp_name}"[:64]
            try:
                conn.execute("INSERT OR IGNORE INTO mt_qbank_knowledge_point (kp_id,subject_id,kp_name,description,difficulty) VALUES (?,?,?,?,?)",
                    (kpid, sid, kp_name, ckey, "medium"))
            except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_qbank_knowledge_point").fetchone()[0]
        print(f"  📚 Knowledge Points: {total}")

    # ── mt_qbank_questions ──
    q_cnt = conn.execute("SELECT COUNT(*) FROM mt_qbank_questions").fetchone()[0]
    if q_cnt == 0:
        contents = conn.execute("SELECT content_key, text, domain, priority FROM mt_iceberg_content_matrix LIMIT 200").fetchall()
        qtypes = ["choice","judge","essay","choice","choice"]
        qseeded = 0
        for idx, (ckey, text, domain, priority) in enumerate(contents):
            if not text or len(text) < 10: continue
            sid_row = conn.execute("SELECT subject_id FROM mt_qbank_subject WHERE subject_name LIKE ?", (f"%{domain}%",)).fetchone()
            if not sid_row: continue
            sid = sid_row[0]
            qid = f"q_{sid}_{idx}_{ckey[-8:]}"
            qtype = _r.choice(qtypes)
            qtext = f"关于「{ckey}」，以下说法正确的是？"
            if qtype == "judge":
                qtext = f"判断: {text[:80]}... — 这个说法是否正确？"
                opts = json.dumps(["正确","错误"], ensure_ascii=False)
                ans = _r.choice(["正确","错误"])
            elif qtype == "essay":
                qtext = f"请解释「{ckey}」的核心概念。"
                opts = "[]"
                ans = text[:200]
            else:
                qtext = f"「{ckey}」的主要内容是什么？"
                opts = json.dumps([text[:60],"干扰项A","干扰项B","干扰项C"], ensure_ascii=False)
                ans = text[:60]
            diff = "hard" if (priority or 100) >= 90 else "easy" if (priority or 100) <= 30 else "medium"
            try:
                conn.execute("INSERT OR IGNORE INTO mt_qbank_questions (question_id,subject_id,question_type,difficulty,question_text,options_json,correct_answer,explanation,confidence,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (qid, sid, qtype, diff, qtext, opts, ans, f"基于 content_matrix ckey={ckey}", round(_r.uniform(0.5,0.9),2), "iceberg_content_matrix"))
                qseeded += 1
            except Exception: pass
        conn.commit()
        # 更新 subject count
        try:
            conn.execute("UPDATE mt_qbank_subject SET question_count = (SELECT COUNT(*) FROM mt_qbank_questions WHERE mt_qbank_questions.subject_id = mt_qbank_subject.subject_id)")
        except Exception: pass
        print(f"  📚 Questions: {qseeded}")

    # ── mt_iceberg_badge ──
    badge_cnt = conn.execute("SELECT COUNT(*) FROM mt_iceberg_badge").fetchone()[0]
    if badge_cnt == 0:
        badges = [
            ("badge_skill_master","技能大师","skill","⚡","某技能 50+ 次调用成功率>90%",json.dumps({"type":"skill_mastery"},ensure_ascii=False),0.3),
            ("badge_skill_apprentice","技能学徒","skill","🌱","首次成功调用某技能",json.dumps({"type":"skill_first_use"},ensure_ascii=False),0.9),
            ("badge_first_employee","初代员工","achievement","🎖️","最早上线的前 5 名 AI 员工",json.dumps({"type":"early_join"},ensure_ascii=False),0.1),
            ("badge_veteran","老兵","achievement","🎗️","累计执行 1000+ hall 任务",json.dumps({"type":"hall_tasks"},ensure_ascii=False),0.4),
            ("badge_workaholic","工作狂","achievement","💼","单日执行 100+ action",json.dumps({"type":"daily_actions"},ensure_ascii=False),0.3),
            ("badge_iceberg_pioneer","冰山先驱","achievement","🧊","参与冰山矩阵首批构建",json.dumps({"type":"iceberg_seed"},ensure_ascii=False),0.5),
            ("badge_finance_pro","金融专家","course","💰","古灵阁沙盘胜率>70%",json.dumps({"type":"finance_winrate"},ensure_ascii=False),0.4),
            ("badge_lang_jlpt_n2","日语 N2","course","🗾","日语 N2 达成",json.dumps({"type":"lang_jlpt"},ensure_ascii=False),0.3),
            ("badge_lang_cefr_b2","英语 B2","course","🌍","英语 CEFR B2",json.dumps({"type":"lang_cefr"},ensure_ascii=False),0.3),
            ("badge_prompt_pro","提示词专家","course","💡","Prompt 7 大框架掌握",json.dumps({"type":"prompt_mastery"},ensure_ascii=False),0.5),
            ("badge_daemon_whisperer","守护灵沟通者","special","👹","让 daemon 零异常运行 7 天",json.dumps({"type":"daemon_uptime"},ensure_ascii=False),0.1),
            ("badge_guardian","铁壁守护","special","🛡️","100+ 巡检全 PASS",json.dumps({"type":"security_perfect"},ensure_ascii=False),0.1),
            ("badge_crisis_handler","危机处理者","special","🚨","成功处理 10+ HEAL_ 事件",json.dumps({"type":"heal_events"},ensure_ascii=False),0.2),
            ("badge_autopilot","自动驾驶员","special","🚗","Andromeda 自动驾驶 72h",json.dumps({"type":"autopilot_hours"},ensure_ascii=False),0.05),
            ("badge_collab_star","协作之星","achievement","⭐","与 5+ 中心协作",json.dumps({"type":"cross_center_collab"},ensure_ascii=False),0.3),
            ("badge_hall_legend","任务厅传奇","achievement","🏆","hall_task TOP 10%",json.dumps({"type":"hall_task_top"},ensure_ascii=False),0.2),
        ]
        for bid, bname, cat, icon, desc, cond, rarity in badges:
            try:
                conn.execute("INSERT OR IGNORE INTO mt_iceberg_badge (badge_id,badge_name,badge_category,icon_emoji,description,condition_json,rarity) VALUES (?,?,?,?,?,?,?)",
                    (bid, bname, cat, icon, desc, cond, rarity))
            except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_iceberg_badge").fetchone()[0]
        print(f"  🏅 Badges: {total}")

    # ── mt_iceberg_achievement ──
    ach_cnt = conn.execute("SELECT COUNT(*) FROM mt_iceberg_achievement").fetchone()[0]
    if ach_cnt == 0:
        top_emps = conn.execute("SELECT employee_id FROM mt_ai_employees ORDER BY rowid LIMIT 10").fetchall()
        for (eid,) in top_emps:
            try:
                conn.execute("INSERT OR IGNORE INTO mt_iceberg_achievement (achievement_id,badge_id,employee_id,context_json) VALUES (?,?,?,?)",
                    (f"ach_{eid}_badge_first_employee", "badge_first_employee", eid,
                     json.dumps({"reason":"初代员工自动授予","auto_seed":True}, ensure_ascii=False)))
            except Exception: pass
            try:
                conn.execute("INSERT OR IGNORE INTO mt_iceberg_achievement (achievement_id,badge_id,employee_id,context_json) VALUES (?,?,?,?)",
                    (f"ach_{eid}_badge_skill_apprentice", "badge_skill_apprentice", eid,
                     json.dumps({"reason":"初始技能学徒授予","auto_seed":True}, ensure_ascii=False)))
            except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_iceberg_achievement").fetchone()[0]
        print(f"  🎖️ Achievements: {total}")

    # ── mt_skill_usage_log ──
    usage_cnt = conn.execute("SELECT COUNT(*) FROM mt_skill_usage_log").fetchone()[0]
    if usage_cnt == 0:
        events = conn.execute("SELECT center_name, event, detail, created_at FROM mt_center_evolution_log ORDER BY created_at DESC LIMIT 500").fetchall()
        daemon_skills = conn.execute("SELECT skill_id FROM mt_skill_registry WHERE category='daemon' AND readiness=1").fetchall()
        daemon_skills = [s[0] for s in daemon_skills] or ["skill_ai_wflow_center"]
        emps = conn.execute("SELECT employee_id FROM mt_ai_employees LIMIT 1").fetchone()
        emp_id = emps[0] if emps else None
        for center, event, detail, ts in events:
            if not center or not ts: continue
            skill_id = _r.choice(daemon_skills)
            try:
                conn.execute("INSERT INTO mt_skill_usage_log (skill_id,employee_id,context,success,created_at) VALUES (?,?,?,?,?)",
                    (skill_id, emp_id, f"center={center},event={event}", 1 if "ALERT" not in (event or "") else 0, ts))
            except Exception: pass
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mt_skill_usage_log").fetchone()[0]
        print(f"  ⚙️ Skill usage logs: {total}")

    # ── mt_lang_session / vocab_review / grammar ──
    sess_cnt = conn.execute("SELECT COUNT(*) FROM mt_lang_session").fetchone()[0]
    if sess_cnt == 0:
        langs = ["ja","en","ko"]
        stypes = ["vocab","grammar","listening"]
        vocab_data = {
            "ja": [("日本","にほん","日本"),("水","みず","水"),("火","ひ","火"),("山","やま","山"),("学校","がっこう","学校")],
            "en": [("hello","","你好"),("world","","世界"),("programming","","编程"),("intelligence","","智能")],
            "ko": [("안녕하세요","","你好"),("사랑","","爱"),("학교","","学校")],
        }
        emps = conn.execute("SELECT employee_id FROM mt_ai_employees LIMIT 3").fetchall()
        for lang in langs:
            for stype in stypes:
                for emp in (emps or [("emp_hr_自动修复工程师",)]):
                    emp_id = emp[0]
                    sid = f"sess_{uuid.uuid4().hex[:10]}"
                    duration = _r.randint(120, 1800) * 1000
                    items = _r.randint(5, 15)
                    correct = int(items * _r.uniform(0.5, 0.95))
                    score = round(correct/items*100, 1) if items > 0 else 0
                    try:
                        conn.execute("INSERT OR IGNORE INTO mt_lang_session (session_id,employee_id,lang,session_type,duration_ms,score,items_count,correct_count) VALUES (?,?,?,?,?,?,?,?)",
                            (sid, emp_id, lang, stype, duration, score, items, correct))
                    except Exception: pass
                    # vocab reviews
                    if stype == "vocab":
                        for w, rd, mn in vocab_data.get(lang, []):
                            res = _r.choice(["correct","wrong","hard","correct","correct"])
                            interval = {"correct":1,"wrong":0,"hard":1}[res] * _r.randint(1,7)
                            try:
                                conn.execute("INSERT INTO mt_lang_vocab_review (session_id,word,reading,meaning,review_result,review_interval) VALUES (?,?,?,?,?,?)",
                                    (sid, w, rd, mn, res, interval))
                            except Exception: pass
                    # grammar
                    if stype == "grammar":
                        for i in range(max(3, correct)):
                            gp = f"{lang} Grammar Point {i+1}"
                            ha = _r.choice([True,False,True,True])
                            try:
                                conn.execute("INSERT INTO mt_lang_grammar (employee_id,grammar_point,lang,practice_text,correct_answer,user_answer,result,hint) VALUES (?,?,?,?,?,?,?,?)",
                                    (emp_id, gp, lang, f"练习: {gp}", "A" if ha else "B", "A" if ha else "A", 1 if ha else 0, "注意时态"))
                            except Exception: pass
        conn.commit()
        s_total = conn.execute("SELECT COUNT(*) FROM mt_lang_session").fetchone()[0]
        v_total = conn.execute("SELECT COUNT(*) FROM mt_lang_vocab_review").fetchone()[0]
        g_total = conn.execute("SELECT COUNT(*) FROM mt_lang_grammar").fetchone()[0]
        print(f"  🗣️ Lang: {s_total} sessions / {v_total} vocab / {g_total} grammar")

    print("🧊 [ICEBERG] All 12 tables ready!\n")


# ═══════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="🧊 Iceberg Schema Seeder")
    parser.add_argument("--create", action="store_true", help="只建表")
    parser.add_argument("--seed", action="store_true", help="只 seed 数据")
    parser.add_argument("--all", action="store_true", help="一键建表 + seed + 验证")
    parser.add_argument("--verify", action="store_true", help="只验证")
    parser.add_argument("--db", default=DB_PATH, help="DB 路径")
    args = parser.parse_args()

    seeder = IcebergSchemaSeeder(db_path=args.db)
    try:
        if args.all:
            seeder.create_all_tables()
            seeder.run_full_seed()
            seeder.verify_all()
        elif args.create:
            seeder.create_all_tables()
        elif args.seed:
            seeder.create_all_tables()  # 确保表存在
            seeder.run_full_seed()
        elif args.verify:
            seeder.verify_all()
        else:
            # 默认: --all
            seeder.create_all_tables()
            seeder.run_full_seed()
            seeder.verify_all()
    finally:
        seeder.close()


if __name__ == "__main__":
    main()
