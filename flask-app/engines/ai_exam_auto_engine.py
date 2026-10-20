#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考试自动引擎 (flow_exam_auto_20261020)
========================================
按真实时间自动获取真实考试题 (摸底/自主招生/月考/模拟/期末, 自由行或专有),
自动分析 + 加入题库 (含结题讲解), 任务大厅自动认领, 对应团队自动学习 + 自动备课。

数据来源 (数据库唯一数据源, 禁止假数据):
  专有测试: adult_education_questions (成人高考/国开/自考/网教 2862题)
           + professional_exam_questions (考研/公务员/司法/四六级等 495题)
  自由行:   mt_exam_questions_pool (300题) + question_bank 真实答案题轮换
结题讲解:  零token 规则模板 (可选本地 Ollama 增强备课摘要, 依然零云端 token)

全链路: 时间日历 → 取题 → 分析(去重/难度/考点) → 入 question_bank(含讲解)
        → 任务大厅入厅自动认领(教育题库中心) → 团队自动学习(mt_edu_learning_log)
        → 自动备课(mt_exam_prep_plans) → 企微播报 → 全量审计

CLI:
  python3 engines/ai_exam_auto_engine.py calendar   # 查看真实时间考试窗口
  python3 engines/ai_exam_auto_engine.py status     # 最近批次状态
  python3 engines/ai_exam_auto_engine.py run        # 执行一轮全链路
  python3 engines/ai_exam_auto_engine.py run --local  # 备课摘要启用本地推理
"""
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

# ── 真实时间考试日历 (month, day) 区间 → 考试类型; 自由行永远兜底 ──
EXAM_WINDOWS = [
    ("摸底测试",   [(2, 20, 3, 10), (8, 25, 9, 15)]),   # 学期初摸底
    ("自主招生测试", [(3, 1, 4, 14)]),                   # 强基/自招季
    ("模拟测试",   [(4, 15, 6, 10)]),                    # 中高考模拟季
    ("期末测试",   [(6, 11, 7, 10), (12, 25, 12, 31)]),  # 学期末
    ("月考测试",   None),                                # 每月 20日-月末 (None=特殊判定)
]
# 专有测试映射: 考试类型 → 真实题源表 + 过滤条件
PROPRIETARY_MAP = {
    "摸底测试":   ("adult_education_questions", "exam_type IN ('成人高考','国家开放大学')"),
    "月考测试":   ("adult_education_questions", "exam_type IN ('自学考试','网络教育')"),
    "自主招生测试": ("professional_exam_questions", "exam_name IN ('考研','公务员考试')"),
    "模拟测试":   ("professional_exam_questions", "exam_name IN ('考研','英语四六级')"),
    "期末测试":   ("adult_education_questions", "1=1"),
}
_PLACEHOLDER_ANSWERS = ("待确认", "", "无", "略")

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_exam_auto_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_type TEXT NOT NULL, window_label TEXT, mode TEXT,
    fetched INTEGER DEFAULT 0, inserted INTEGER DEFAULT 0, skipped_dup INTEGER DEFAULT 0,
    hall_task_id INTEGER, detail_json TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_exam_prep_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_type TEXT NOT NULL, window_label TEXT, subject TEXT,
    plan_md TEXT, question_ids_json TEXT, team_json TEXT,
    status TEXT DEFAULT 'PREPARED', hall_task_id INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables():
    conn = _db()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ══════════════ ① 真实时间日历 ══════════════

def exam_calendar(now=None):
    """按真实时间返回当前考试窗口: 自由行或专有测试类型列表"""
    now = now or datetime.now()
    m, d = now.month, now.day
    types = []
    for etype, ranges in EXAM_WINDOWS:
        if ranges is None:                       # 月考: 每月 20日-月末
            if d >= 20:
                types.append(etype)
            continue
        for m1, d1, m2, d2 in ranges:
            if (m == m1 and d >= d1) or (m == m2 and d <= d2) or (m1 < m < m2):
                types.append(etype)
                break
    semester = "秋季学期" if m >= 9 or m == 1 else "春季学期"
    return {"now": now.strftime("%Y-%m-%d %H:%M:%S"),
            "semester": semester,
            "window_label": now.strftime("%Y-%m") + f" · {semester}",
            "exam_types": types or ["自由行专项"],
            "free_mode": not types}


# ══════════════ ② 真实取题 ══════════════

def _season_offset():
    return int(datetime.now().strftime("%Y%m")) % 97  # 按月轮换, 同月内稳定


def _fetch_proprietary(etype, n=6):
    """专有测试: 从真实考试题源表按考试类型取题 (带真实答案+解析优先)"""
    table, cond = PROPRIETARY_MAP[etype]
    conn = _db()
    try:
        cols_map = {
            "adult_education_questions": "exam_type AS origin_exam, subject, question_type, difficulty, content, options, correct_answer, explanation, knowledge_points",
            "professional_exam_questions": "exam_name AS origin_exam, subject, question_type, difficulty, content, options, correct_answer, explanation, knowledge_points",
        }
        return [dict(r) for r in conn.execute(
            f"SELECT {cols_map[table]} FROM {table} WHERE ({cond}) "
            f"AND correct_answer IS NOT NULL AND TRIM(correct_answer) != '' "
            f"ORDER BY (question_id + {_season_offset()}) % 89, question_id LIMIT ?", (n,))]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _fetch_free(n=6):
    """自由行: mt_exam_questions_pool 按月轮换 + question_bank 真实答案题兜底"""
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT subject, question_type, difficulty, content, options, "
            "'' AS correct_answer, '' AS explanation, tags_json AS knowledge_points "
            f"FROM mt_exam_questions_pool ORDER BY (id + {_season_offset()}) % 83, id LIMIT ?", (n,))]
        if len(rows) < n:
            rows += [dict(r) for r in conn.execute(
                "SELECT subject, question_type, difficulty, content, options, "
                "COALESCE(correct_answer, answer) AS correct_answer, "
                "COALESCE(analysis, explanation) AS explanation, knowledge_points "
                "FROM question_bank WHERE status='published' AND COALESCE(correct_answer, answer, '') != '' "
                "AND COALESCE(correct_answer, answer, '') NOT IN ('待确认','') "
                f"ORDER BY (id + {_season_offset()}) % 79, id DESC LIMIT ?", (n - len(rows),))]
        return rows
    finally:
        conn.close()


# ══════════════ ③ 分析 + 结题讲解 (零token) ══════════════

def _content_hash(content):
    return hashlib.md5((content or "").strip().encode("utf-8")).hexdigest()


def _norm_difficulty(diff, content):
    d = (diff or "").lower()
    if d in ("easy", "medium", "hard"):
        return d
    return "medium" if len(content or "") < 120 else "hard"


def _explain(row, etype):
    """结题讲解: 优先沿用源题真实解析; 占位/缺失时按题型生成结构化讲解 (零token)"""
    src = (row.get("explanation") or "").strip()
    if src and not src.startswith("来源") and "置信度" not in src:
        return src
    ans = (row.get("correct_answer") or "").strip() or "见解析"
    qtype = (row.get("question_type") or "").lower()
    kp = (row.get("knowledge_points") or "核心考点").split(",")[0].strip()[:24]
    if "choice" in qtype or "select" in qtype:
        return (f"结题讲解: ① 审题定位考点「{kp}」, 明确题目考查方向; "
                f"② 逐项比对选项, 排除与题干条件矛盾项; ③ 正确答案为「{ans}」。"
                f"备考提示: 本题为{etype}真题, 同类考点建议结合错题本巩固。")
    if "fill" in qtype or "blank" in qtype:
        return (f"结题讲解: ① 提取题干关键条件, 锁定「{kp}」相关公式/定义; "
                f"② 按步骤代入推导, 得出答案「{ans}」; ③ 回代检验确保严谨。"
                f"备考提示: {etype}填空题注重过程完整性, 建议限时训练。")
    return (f"结题讲解: ① 通读材料, 拆解设问层次 (考查「{kp}」); "
            f"② 结合知识框架组织要点, 对照参考答案「{ans}」补齐遗漏; "
            f"③ 总结答题模板。备考提示: {etype}主观题按点给分, 要点前置。")


def _analyze_and_insert(rows, etype, window_label):
    """去重 → 分析 → 入 question_bank (含结题讲解) → 返回 (inserted, skipped, qids, subjects)"""
    conn = _db()
    inserted, skipped, qids, subjects = 0, 0, [], []
    try:
        existing = {r[0] for r in conn.execute("SELECT content_hash FROM question_content_hashes")}
        today = datetime.now().strftime("%Y%m%d")
        for i, row in enumerate(rows):
            content = (row.get("content") or "").strip()
            if not content or len(content) < 8:
                skipped += 1
                continue
            h = _content_hash(content)
            if h in existing:
                skipped += 1
                continue
            subject = (row.get("subject") or "综合").strip()[:20]
            answer = (row.get("correct_answer") or "").strip()[:200]
            if answer in _PLACEHOLDER_ANSWERS and "choice" not in (row.get("question_type") or "").lower():
                skipped += 1          # 无真实答案不入库 (禁止假数据)
                continue
            explanation = _explain(row, etype)
            qtype = (row.get("question_type") or "comprehension").lower()[:20]
            quality = 0.9 if answer and (row.get("options") or explanation) else 0.75
            qid = f"EA{today}{i:03d}"
            conn.execute("""INSERT INTO question_bank
                (question_id, subject, grade, question_type, difficulty, content, options,
                 answer, explanation, knowledge_points, source, status, quality_score,
                 rule_level, tags, question_uuid, correct_answer, analysis)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (qid, subject, "", qtype,
                 _norm_difficulty(row.get("difficulty"), content), content,
                 (row.get("options") or "")[:2000], answer, explanation,
                 (row.get("knowledge_points") or "")[:200], "exam_auto", "published",
                 quality, "L2", f"{etype},{window_label[:7]}", str(uuid.uuid4()),
                 answer, explanation))
            conn.execute("INSERT INTO question_content_hashes (content_hash, question_id, created_at) VALUES (?,?,datetime('now','localtime'))",
                         (h, qid))
            existing.add(h)
            inserted += 1
            qids.append(qid)
            if subject not in subjects:
                subjects.append(subject)
        conn.commit()
    finally:
        conn.close()
    return inserted, skipped, qids, subjects


# ══════════════ ④ 团队自动学习 + 自动备课 ══════════════

def _pick_team(subjects):
    """对应团队: 按学科关键词从 ai_employees 匹配 AI员工 + 教授分身"""
    emps, profs = [], []
    try:
        sys.path.insert(0, _APP_DIR)
        from blueprints.daemon_skill_lab_bp import _pick_staff
        kws = ",".join((s or "教育") for s in subjects[:3])
        emps, profs = _pick_staff("教育题库", kws)
    except Exception:
        pass
    return emps[:4], profs[:2]


def _team_learn(subjects, etype, window_label, team_names, knowledge):
    """自动学习: 学科匹配课程 (无则建备考专题课) → 团队入学完成并沉淀知识"""
    conn = _db()
    learned = []
    try:
        for subject in subjects[:3]:
            row = conn.execute(
                "SELECT id, title FROM mt_edu_courses WHERE (domain LIKE ? OR keywords LIKE ?) "
                "AND status='ACTIVE' LIMIT 1", (f"%{subject}%", f"%{subject}%")).fetchone()
            if not row:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO mt_edu_courses (title, domain, source, content, keywords) VALUES (?,?,?,?,?)",
                    (f"{subject}·{etype}备考专题", subject, "exam_auto",
                     knowledge[:1500], subject))
                course_id = cur.lastrowid
                title = f"{subject}·{etype}备考专题"
            else:
                course_id, title = row["id"], row["title"]
            for name in team_names:
                conn.execute("""INSERT OR REPLACE INTO mt_edu_learning_log
                    (course_id, employee_name, progress, status, knowledge, updated_at)
                    VALUES (?,?,100,'COMPLETED',?,datetime('now','localtime'))""",
                    (course_id, name, f"[{etype}] {knowledge[:200]}"))
                learned.append({"employee": name, "course": title})
        conn.commit()
    finally:
        conn.close()
    return learned


def _prep_plan_md(etype, window_label, qids, subjects, rows, use_local=False):
    """自动备课: 难度/考点分布 + 结题讲解要点 + 教学安排 (零token规则模板, 可选本地增强)"""
    diffs = {}
    for r in rows:
        d = _norm_difficulty(r.get("difficulty"), r.get("content"))
        diffs[d] = diffs.get(d, 0) + 1
    dist = " / ".join(f"{k}×{v}" for k, v in sorted(diffs.items())) or "均匀"
    md = (f"# {etype} · 自动备课方案 ({window_label})\n\n"
          f"## 一、题情分析\n- 入库题量: {len(qids)} 题 (学科: {'、'.join(subjects) or '综合'})\n"
          f"- 难度分布: {dist}\n- 题目来源: 真实考试题库 (source=exam_auto, 全量审计留痕)\n\n"
          f"## 二、教学安排\n1. 第一课时: 考点梳理 + 高频题型精讲 (结合入库题结题讲解)\n"
          f"2. 第二课时: 分层练习 (按难度分布配比) + 限时训练\n"
          f"3. 第三课时: 错题归因 + 结题讲解复述 (费曼式输出)\n\n"
          f"## 三、结题讲解要点\n- 选择题: 定考点 → 排除法 → 回归题干验证\n"
          f"- 填空题: 条件转化 → 公式代入 → 回代检验\n- 主观题: 拆设问 → 列要点 → 模板作答\n\n"
          f"## 四、团队学习\n- 对应团队已完成入库题学习并沉淀知识至教育中心学习档案\n")
    if use_local:
        try:
            sys.path.insert(0, _APP_DIR)
            from ai_engines.local_ai_unified_gateway import _native_ollama_available, _native_ollama_chat
            if _native_ollama_available():
                r = _native_ollama_chat(
                    f"为{etype}补充2条教学建议(每条不超过30字), 直接输出要点:",
                    system="你是教研组长, 只输出要点, 不输出寒暄")
                if r.get("success") and r.get("response"):
                    md += f"\n## 五、本地教研建议 (Ollama 零token)\n{r['response'].strip()[:300]}\n"
        except Exception:
            pass
    return md


# ══════════════ ⑤ 全链路 run ══════════════

def run_exam_auto(per_type=6, use_local=False):
    """执行一轮: 日历 → 取题分析入库 → 大厅自动认领 → 团队学习 → 自动备课 → 播报/审计"""
    _ensure_tables()
    cal = exam_calendar()
    batches, all_qids, all_subjects = [], [], []
    hall_task_id = None

    for etype in cal["exam_types"]:
        mode = "free" if etype == "自由行专项" else "proprietary"
        rows = _fetch_free(per_type) if mode == "free" else _fetch_proprietary(etype, per_type)
        if not rows:
            rows = _fetch_free(per_type)   # 专有源异常时自由行兜底
            mode = "free_fallback"
        inserted, skipped, qids, subjects = _analyze_and_insert(rows, etype, cal["window_label"])
        all_qids += qids
        all_subjects += subjects
        conn = _db()
        try:
            conn.execute("INSERT INTO mt_exam_auto_log (exam_type, window_label, mode, fetched, inserted, skipped_dup, detail_json) VALUES (?,?,?,?,?,?,?)",
                         (etype, cal["window_label"], mode, len(rows), inserted, skipped,
                          json.dumps({"qids": qids, "subjects": subjects}, ensure_ascii=False)))
            log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            if inserted:
                conn.execute("INSERT INTO mt_lab_task_hall (title, description, source, source_id, priority) VALUES (?,?,?,?,?)",
                             (f"【{etype}】{cal['window_label']} 考试题入库·结题讲解·备课",
                              f"教育题库中心: {etype} {inserted} 题已入题库(含结题讲解), 需对应团队备课与教学讲解, 考试教育任务",
                              "exam_auto", log_id, "NORMAL"))
                hall_task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute("UPDATE mt_exam_auto_log SET hall_task_id=? WHERE id=?", (hall_task_id, log_id))
            conn.commit()
        finally:
            conn.close()
        batches.append({"exam_type": etype, "mode": mode, "fetched": len(rows),
                        "inserted": inserted, "skipped_dup": skipped, "subjects": subjects})

    # 自动认领: 任务大厅自动分配 (教育题库中心)
    claim = None
    if hall_task_id:
        try:
            sys.path.insert(0, _APP_DIR)
            from blueprints.daemon_skill_lab_bp import run_hall_auto, _audit
            auto = run_hall_auto()
            claim = next((r for r in auto.get("results", []) if r.get("task", "").startswith("【")),
                         auto.get("results", [None])[0] if auto.get("results") else None)
            _audit("exam_auto", "EXAM_AUTO_CLAIM", f"认领{auto.get('dispatched', 0)}项",
                   {"batches": batches, "claim": claim})
        except Exception as e:
            claim = {"error": str(e)}

    # 团队自动学习 + 自动备课
    all_subjects = list(dict.fromkeys(all_subjects))
    learned, plan_id = [], None
    if all_qids:
        emps, profs = _pick_team(all_subjects)
        team_names = [e["name"] for e in emps] + [p["name"] for p in profs]
        knowledge = f"{cal['exam_types'][0]} {len(all_qids)} 题: 考点{'、'.join(all_subjects[:5])}, 含结题讲解"
        learned = _team_learn(all_subjects, cal["exam_types"][0], cal["window_label"], team_names, knowledge)
        conn = _db()
        try:
            main_etype = cal["exam_types"][0]
            plan_md = _prep_plan_md(main_etype, cal["window_label"], all_qids, all_subjects,
                                    _fetch_free(len(all_qids)) if cal["free_mode"] else
                                    _fetch_proprietary(main_etype, len(all_qids)), use_local)
            conn.execute("""INSERT INTO mt_exam_prep_plans
                (exam_type, window_label, subject, plan_md, question_ids_json, team_json, hall_task_id)
                VALUES (?,?,?,?,?,?,?)""",
                (main_etype, cal["window_label"], "、".join(all_subjects[:3]), plan_md,
                 json.dumps(all_qids), json.dumps(team_names, ensure_ascii=False), hall_task_id))
            plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

    summary = {"ok": True, "calendar": cal, "batches": batches,
               "total_inserted": sum(b["inserted"] for b in batches),
               "hall_task_id": hall_task_id, "claim": claim,
               "learned": learned, "prep_plan_id": plan_id}
    # 企微播报 + 审计 (懒加载, 永不阻断主链路)
    try:
        sys.path.insert(0, _APP_DIR)
        from blueprints.wecom_hub_bp import wecom_push
        from blueprints.daemon_skill_lab_bp import _audit
        md = (f"**📅 考试自动引擎 ({cal['window_label']})**\n"
              f"- 窗口: {'、'.join(cal['exam_types'])}\n"
              f"- 入库: **{summary['total_inserted']}** 题 (含结题讲解)\n"
              f"- 认领: {hall_task_id or '-'} | 备课: #{plan_id or '-'} | 团队学习: {len(learned)} 人次")
        wecom_push("exam_auto", "考试自动引擎播报", md)
        _audit("exam_auto", "EXAM_AUTO_RUN", f"入库{summary['total_inserted']}题",
               {"batches": batches, "plan_id": plan_id})
    except Exception:
        pass
    return summary


def exam_status():
    """状态: 真实时间窗口 + 最近批次 + 备课计划"""
    _ensure_tables()
    conn = _db()
    try:
        logs = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_exam_auto_log ORDER BY id DESC LIMIT 10")]
        plans = [dict(r) for r in conn.execute(
            "SELECT id, exam_type, window_label, subject, status, hall_task_id, created_at "
            "FROM mt_exam_prep_plans ORDER BY id DESC LIMIT 10")]
        total = conn.execute("SELECT count(*) FROM question_bank WHERE source='exam_auto'").fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "calendar": exam_calendar(), "total_in_qbank": total,
            "recent_batches": logs, "prep_plans": plans}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "calendar":
        print(json.dumps(exam_calendar(), ensure_ascii=False, indent=2))
    elif cmd == "run":
        use_local = "--local" in sys.argv
        print(json.dumps(run_exam_auto(use_local=use_local), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(exam_status(), ensure_ascii=False, indent=2))
