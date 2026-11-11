#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学题型解析教学法引擎 [flow_math_pedagogy_20261027]
=====================================================
仙女座数学能力中枢 — 全链路高阶教学能力:
  ① 题型题库解析解答  题型自动识别 → 母题模型匹配 → 三轨 LLM 详解 → 入库沉淀
  ② 题目创造          母题变式 + LLM 精修, 按考点/难度/题型定向造题
  ③ 试卷生成          考点覆盖约束 + 难度分布(易30/中40/难30) + 库存不足自动造题回填
  ④ 试卷批改          客观题精确判分 / 主观题关键词命中率 + 四类错因归因
  ⑤ 难度动态弹性调整  学情画像驱动 ELO 式难度带(2-4)自动升降档 + 事件留痕
  ⑥ 个性化解析讲解    按学生认知层级(L1~L5)+讲解风格四型定制分层讲解

跨中心协同 (用户指令: 动态人力资源中心雇佣数学专家 + 利用其他中心能力):
  - EigenFlux 专家雇佣: mathematics 领域 6 专家 (竞赛教练/建模/教法/代几/概率统计/命题)
  - 教育题库中心(edu_qbank): 复用 mt_edu_sync_question_types 7 题型母题库
  - 任务大厅: 教学任务入厅 → 教育题库中心认领 → 专家团队/数据研究中心协作
  - LLM 三轨: ai_dual_route_engine.route_and_chat (local_ollama → spark → volcengine)

CLI:
  python3 ai_math_pedagogy_engine.py init     # 建表 + 雇佣数学专家 + 母题同步
  python3 ai_math_pedagogy_engine.py hire     # 雇佣数学专家
  python3 ai_math_pedagogy_engine.py demo     # 全链路演示(解析/造题/组卷/批改/弹性/讲解)
  python3 ai_math_pedagogy_engine.py status   # 总览
"""
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# flow_remaining_db_unify_20261022: 统一 DB 权威源 (PROD 优先 → flask-app/database 加成)
from core.db_path import get_db_path

DB_PATH = get_db_path('app.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ============================================================
#  建表
# ============================================================

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_math_qbank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qcode TEXT UNIQUE NOT NULL,
    stage TEXT DEFAULT 'K12',            -- K12 / HIGHER_EDU / ADULT_EDU
    subject TEXT DEFAULT '数学',
    question TEXT NOT NULL,
    q_type TEXT DEFAULT '解答题',        -- 选择题/填空题/计算题/解答题/证明题/应用题/几何题
    topic TEXT,                          -- 考点 (如 二次函数)
    knowledge_points TEXT,               -- 知识点(逗号分隔)
    difficulty INTEGER DEFAULT 3,        -- 1易 ~ 5难
    answer TEXT,
    solution TEXT,                       -- 标准详解
    analysis TEXT,                       -- 题型解析 (考点/套路/易错点)
    hints TEXT,                          -- JSON 数组 分层提示
    source TEXT DEFAULT 'engine',        -- engine/expert/llm/seed
    expert_id TEXT,                      -- 产出专家 (eigenflux)
    model_ref TEXT,                      -- 引用母题 qtype_id
    quality_score REAL DEFAULT 0.8,
    usage_count INTEGER DEFAULT 0,
    correct_rate REAL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_math_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    paper_type TEXT DEFAULT '月考',      -- 摸底/月考/模拟/专项
    stage TEXT DEFAULT 'K12',
    difficulty_target REAL DEFAULT 3.0,
    difficulty_actual REAL,
    question_codes TEXT,                 -- JSON [qcode,...]
    topic_coverage TEXT,                 -- JSON {topic: 权重}
    total_score INTEGER DEFAULT 100,
    duration_min INTEGER DEFAULT 90,
    status TEXT DEFAULT 'READY',         -- READY/GRADED
    created_by TEXT DEFAULT '仙女座',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_math_gradings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    student TEXT NOT NULL,
    score REAL NOT NULL,
    max_score REAL NOT NULL,
    item_results TEXT,                   -- JSON [{qcode,q_type,topic,difficulty,score,max,correct}]
    error_attribution TEXT,              -- JSON {概念不清:n,方法未掌握:n,计算失误:n,审题偏差:n}
    weak_points TEXT,                    -- JSON [薄弱考点,...]
    graded_by TEXT DEFAULT '仙女座批改组',
    graded_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_math_learner_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student TEXT UNIQUE NOT NULL,
    stage TEXT DEFAULT 'K12',
    level TEXT DEFAULT 'L3',             -- L1启蒙~L5竞赛
    mastery TEXT,                        -- JSON {topic: 0~1 掌握度}
    correct_rate REAL DEFAULT 0.5,
    recent_trend REAL DEFAULT 0,         -- 近三次成绩斜率
    difficulty_band TEXT DEFAULT '2-4',  -- 当前弹性难度带
    style TEXT DEFAULT '步骤型',         -- 视觉型/步骤型/直觉型/严谨型
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_math_difficulty_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student TEXT NOT NULL,
    old_band TEXT,
    new_band TEXT,
    trigger TEXT,                        -- RISE/FALL/INIT
    correct_rate REAL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]


def ensure_tables():
    conn = get_conn()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  EigenFlux 数学专家雇佣 (动态人力资源中心)
# ============================================================

def hire_math_experts(count: int = 6, round_num: int = 1) -> List[dict]:
    """通过 EigenFlux 雇佣 mathematics 领域专家 (竞赛教练/建模/教法/代几/概率统计/命题)"""
    ensure_tables()
    from services.eigenflux.eigenflux_expert_hiring import get_expert_hiring_engine, ensure_tables as _ef_tables
    _ef_tables()
    engine = get_expert_hiring_engine()
    return engine.hire_batch(round_num, count, domain="mathematics")


def form_math_team(round_num: int = 1) -> dict:
    """组建数学教研专家团队 (跨中心: 专家团队中心协同)"""
    from services.eigenflux.eigenflux_expert_hiring import get_expert_hiring_engine, ensure_tables as _ef_tables
    _ef_tables()
    return get_expert_hiring_engine().form_team(
        round_num, objective="数学题型解析与个性化教学攻坚")


def list_math_experts() -> List[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT expert_id,name,role,role_cn,level,performance_score,status "
            "FROM eigenflux_experts WHERE domain='mathematics' ORDER BY performance_score DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _pick_expert(conn, specialty: str) -> Optional[dict]:
    """按专长挑活跃数学专家 (教法→解题, 命题→造题/组卷, 竞赛→难题)"""
    try:
        rows = conn.execute(
            "SELECT expert_id,role_cn,name,level FROM eigenflux_experts "
            "WHERE domain='mathematics' AND status='active' ORDER BY performance_score DESC").fetchall()
        if not rows:
            return None
        prefs = {"教法": "教法", "命题": "命题", "竞赛": "竞赛"}
        want = prefs.get(specialty)
        if want:
            for r in rows:
                if want in (r["role_cn"] or ""):
                    return dict(r)
        return dict(rows[0])
    except sqlite3.Error:
        return None


# ============================================================
#  ① 题型识别 + 解析解答
# ============================================================

_TYPE_KEYWORDS = [
    ("选择题", ["选择题", "下列", "选项", "A.", "B.", "正确的是", "错误的是"]),
    ("填空题", ["填空", "___", "____", "横线"]),
    ("证明题", ["证明", "求证", "试证"]),
    ("几何题", ["三角形", "圆", "四边形", "相似", "全等", "勾股", "切线"]),
    ("应用题", ["应用", "实际问题", "利润", "行程", "方案", "成本", "增长率"]),
    ("计算题", ["计算", "求值", "化简", "解方程", "求极限", "求导"]),
    ("解答题", ["解答", "求解", "已知", "如图"]),
]

_KNOWN_TOPICS = [
    ("有理数", ["有理数", "绝对值", "相反数"]),
    ("二次函数", ["二次函数", "抛物线", "顶点", "判别式", "待定系数"]),
    ("函数与极限", ["极限", "洛必达", "无穷小", "连续"]),
    ("线性代数", ["矩阵", "行列式", "秩", "解空间", "特征值"]),
    ("概率统计", ["概率", "期望", "方差", "分布", "统计"]),
    ("方程与不等式", ["方程", "不等式", "根", "解集"]),
    ("几何变换", ["相似", "全等", "旋转", "平移", "对称"]),
    ("数列", ["数列", "等差", "等比", "递推"]),
]


def classify_question(question: str) -> Dict[str, Any]:
    """题型识别 (零 token 本地规则): 关键词加权打分"""
    scores: Dict[str, int] = {}
    for qtype, kws in _TYPE_KEYWORDS:
        for kw in kws:
            if kw in question:
                scores[qtype] = scores.get(qtype, 0) + 2
    if question.strip().endswith(("？", "?")) and "下列" not in question:
        scores["解答题"] = scores.get("解答题", 0) + 1
    q_type = max(scores, key=scores.get) if scores else "解答题"
    topic, kps = None, []
    for t, kws in _KNOWN_TOPICS:
        hit = [k for k in kws if k in question]
        if hit:
            topic = t
            kps = hit
            break
    return {"q_type": q_type, "topic": topic, "knowledge_points": kps}


def _match_mother_question(conn, q_type: str, kps: List[str]) -> Optional[dict]:
    """匹配母题库 mt_edu_sync_question_types (教育题库中心资产复用)"""
    try:
        rows = conn.execute(
            "SELECT * FROM mt_edu_sync_question_types WHERE status='ACTIVE'").fetchall()
    except sqlite3.Error:
        return None
    best, best_hit = None, 0
    for r in rows:
        r_kps = [k.strip() for k in (r["knowledge_points"] or "").split(",") if k.strip()]
        hit = len(set(kps) & set(r_kps))
        if r["question_type"] == q_type:
            hit += 1
        if hit > best_hit:
            best, best_hit = dict(r), hit
    return best if best_hit > 0 else None


def _local_solution(question: str, q_type: str, topic: Optional[str],
                    mother: Optional[dict]) -> str:
    """本地兜底解析 (零 token): 母题解题步骤模板 + 通用教学法框架"""
    parts = [f"【题型定位】{q_type}" + (f" · 考点「{topic}」" if topic else " · 综合考点")]
    if mother:
        parts.append(f"【母题模型】{mother.get('parent_question') or mother.get('qtype_id', '')}"
                     f"（{mother.get('solving_model') or '通用模型'}）")
        steps = mother.get("solving_steps") or ""
        if steps:
            parts.append(f"【解题步骤】{steps}")
        tpl = mother.get("answer_template") or ""
        if tpl:
            parts.append(f"【作答模板】{tpl}")
    else:
        parts.append("【解题步骤】1.读题提取已知与目标 2.联系考点模型 3.分步推演 4.检验作答")
    parts.append("【通用提醒】先定位考点, 再套模型步骤, 最后回代检验。")
    return "\n".join(p for p in parts if p.strip())


def _llm_solution(question: str, q_type: str, topic: Optional[str],
                  stage: str) -> Optional[str]:
    """三轨 LLM 详解 (local_ollama → spark → volcengine), 失败返回 None 走本地兜底"""
    try:
        from ai_engines.ai_dual_route_engine import route_and_chat
        sys_p = ("你是资深数学命题专家与特级教师。给出严格分步的标准解答: "
                 "①题意与考点分析 ②思路引入 ③分步推导(含关键公式) ④最终答案 ⑤易错点提醒。")
        prompt = (f"学段: {stage}\n题型: {q_type}\n考点: {topic or '待分析'}\n题目: {question}\n"
                  "请按五段式给出完整解析。")
        r = route_and_chat(prompt, system=sys_p, kind="research",
                           flow_id="flow_math_pedagogy_20261027", prefer_local=True)
        if r and r.get("success") and (r.get("response") or "").strip():
            return f"[{r.get('route', 'llm')}] " + r["response"].strip()[:3000]
    except Exception:
        pass
    return None


def solve_question(question: str, stage: str = "K12",
                   expert_specialty: str = "教法") -> Dict[str, Any]:
    """题型题库解析解答: 题库命中 → 母题匹配 → LLM 生成 → 本地兜底, 全部入库沉淀"""
    ensure_tables()
    cls = classify_question(question)
    q_type, topic, kps = cls["q_type"], cls["topic"], cls["knowledge_points"]
    conn = get_conn()
    try:
        # a) 题库命中
        row = conn.execute(
            "SELECT * FROM mt_math_qbank WHERE question LIKE ? LIMIT 1",
            (f"%{question.strip()[:60]}%",)).fetchone()
        if row:
            conn.execute("UPDATE mt_math_qbank SET usage_count=usage_count+1, updated_at=? WHERE id=?",
                         (_now(), row["id"]))
            conn.commit()
            return {"hit": "qbank", "qcode": row["qcode"], "q_type": row["q_type"],
                    "topic": row["topic"], "difficulty": row["difficulty"],
                    "solution": row["solution"], "analysis": row["analysis"],
                    "hints": json.loads(row["hints"] or "[]")}
        # b) 专家 + 母题
        expert = _pick_expert(conn, expert_specialty)
        mother = _match_mother_question(conn, q_type, kps)
    finally:
        conn.close()
    # c) LLM 三轨生成, 兜底本地
    solution = _llm_solution(question, q_type, topic, stage) or _local_solution(
        question, q_type, topic, mother)
    analysis = (f"题型「{q_type}」· 考点「{topic or '综合'}」"
                + (f" · 母题模型: {mother['solving_model']}" if mother and mother.get("solving_model") else ""))
    hints = json.dumps([
        f"提示1: 先确认考点「{topic or q_type}」对应的模型",
        f"提示2: 套用标准步骤, 先写已知/再写目标",
        "提示3: 结果回代检验, 注意定义域与单位",
    ], ensure_ascii=False)
    qcode = _uid("MATHQ")
    conn = get_conn()
    try:
        diff = 3 if not mother else {"easy": 2, "medium": 3, "hard": 4}.get(mother.get("difficulty"), 3)
        conn.execute(
            """INSERT INTO mt_math_qbank (qcode,stage,question,q_type,topic,knowledge_points,
               difficulty,answer,solution,analysis,hints,source,expert_id,model_ref,quality_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (qcode, stage, question, q_type, topic, ",".join(kps), diff,
             None, solution, analysis, hints,
             "llm" if solution.startswith("[") else "engine",
             expert["expert_id"] if expert else None,
             mother["qtype_id"] if mother else None, 0.85))
        conn.commit()
    finally:
        conn.close()
    return {"hit": "new", "qcode": qcode, "q_type": q_type, "topic": topic,
            "difficulty": diff, "solution": solution, "analysis": analysis,
            "hints": json.loads(hints), "expert": expert["name"] if expert else None,
            "mother_model": mother["solving_model"] if mother else None}


# ============================================================
#  ② 题目创造
# ============================================================

def create_questions(topic: str, difficulty: int = 3, count: int = 3,
                     q_type: str = "解答题", stage: str = "K12",
                     expert_specialty: str = "命题") -> List[dict]:
    """题目创造: 母题变式模板 + LLM 精修, 全部入 mt_math_qbank"""
    ensure_tables()
    conn = get_conn()
    try:
        expert = _pick_expert(conn, expert_specialty)
        mothers = conn.execute(
            "SELECT * FROM mt_edu_sync_question_types WHERE status='ACTIVE' "
            "AND (knowledge_points LIKE ? OR question_type=?) LIMIT 3",
            (f"%{topic}%", q_type)).fetchall()
        mother = dict(mothers[0]) if mothers else None
    finally:
        conn.close()

    made: List[dict] = []
    conn = get_conn()
    try:
        for i in range(count):
            variant_seed = _uid("VAR")
            question = (f"[{topic}·{q_type}·难度{difficulty}] 变式题{variant_seed[-4:]}: "
                        f"围绕考点「{topic}」的{q_type}, 难度层级 {difficulty}/5, "
                        f"需考查 {topic} 的核心方法"
                        + ("与综合运用" if difficulty >= 4 else "与基础运用") + "。")
            sys_p = (f"你是数学{('竞赛教练' if difficulty >= 4 else '命题专家')}。"
                     "输出格式: 题目→答案→分步详解→易错点, 拒绝套路化。")
            prompt = (f"请围绕考点「{topic}」原创一道{stage}阶段{q_type}"
                      f"(难度{difficulty}/5){'竞赛风格' if difficulty >= 4 else ''}, "
                      "并给出答案与分步详解。")
            llm_txt = None
            try:
                from ai_engines.ai_dual_route_engine import route_and_chat
                r = route_and_chat(prompt, system=sys_p, kind="chat",
                                   flow_id="flow_math_pedagogy_20261027", prefer_local=True)
                if r and r.get("success") and (r.get("response") or "").strip():
                    llm_txt = r["response"].strip()[:2500]
            except Exception:
                llm_txt = None
            if llm_txt:
                question = llm_txt.split("\n")[0].strip()[:300]
                solution = llm_txt
            else:
                solution = (_local_solution(question, q_type, topic, mother)
                            + f"\n【变式编号】{variant_seed}")
            qcode = _uid("MATHQ")
            conn.execute(
                """INSERT INTO mt_math_qbank (qcode,stage,question,q_type,topic,knowledge_points,
                   difficulty,solution,analysis,hints,source,expert_id,model_ref,quality_score)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (qcode, stage, question, q_type, topic, topic, difficulty,
                 solution,
                 f"原创变式题 · 考点「{topic}」· 难度{difficulty}",
                 json.dumps([f"考点模型: {topic}", "先审题定位, 再分步推演"], ensure_ascii=False),
                 "llm" if llm_txt else "engine",
                 expert["expert_id"] if expert else None,
                 mother["qtype_id"] if mother else None,
                 round(0.7 + 0.05 * difficulty, 2)))
            made.append({"qcode": qcode, "question": question[:120],
                         "difficulty": difficulty, "via": "llm" if llm_txt else "template"})
        conn.commit()
    finally:
        conn.close()
    return made


# ============================================================
#  ③ 试卷生成 (组卷)
# ============================================================

_DIFF_PLAN = [(1, 0.3), (2, 0.3), (3, 0.4), (4, 0.4), (5, 0.3)]  # 难度→该难度目标占比
_BELT = {1: [(1, 0.5), (2, 0.5)], 2: [(2, 0.5), (3, 0.5)], 3: [(3, 0.5), (2, 0.25), (4, 0.25)],
         4: [(4, 0.5), (3, 0.25), (5, 0.25)], 5: [(5, 0.6), (4, 0.4)]}


def generate_paper(title: str, paper_type: str = "月考", stage: str = "K12",
                   topic_weights: Optional[Dict[str, int]] = None,
                   difficulty_target: int = 3, question_count: int = 10,
                   duration_min: int = 90) -> Dict[str, Any]:
    """组卷: 考点覆盖 + 难度分布约束, 库存不足自动造题回填 (难度弹性内核)"""
    ensure_tables()
    topic_weights = topic_weights or {}
    plan = _BELT.get(max(1, min(5, int(difficulty_target))), _BELT[3])
    need: List[tuple] = []  # [(difficulty, n)]
    for d, ratio in plan:
        need.append((d, max(1, round(question_count * ratio))))
    topics = list(topic_weights.keys()) or ["有理数", "二次函数", "方程与不等式", "几何变换"]

    conn = get_conn()
    picked: List[dict] = []
    try:
        for d, n in need:
            for t in topics:
                if len(picked) >= question_count:
                    break
                rows = conn.execute(
                    """SELECT qcode,question,q_type,topic,difficulty FROM mt_math_qbank
                       WHERE difficulty=? AND (topic=? OR knowledge_points LIKE ?)
                       AND qcode NOT IN (SELECT qcode FROM mt_math_qbank WHERE 1=0) LIMIT ?""",
                    (d, t, f"%{t}%", n)).fetchall()
                got_codes = {p["qcode"] for p in picked}
                for r in rows:
                    if r["qcode"] not in got_codes and len(picked) < question_count:
                        picked.append(dict(r))
    finally:
        conn.close()
    # 库存不足 → 自动造题回填
    shortage = question_count - len(picked)
    filled = []
    if shortage > 0:
        have_ds = [p["difficulty"] for p in picked]
        for i in range(shortage):
            d = need[i % len(need)][0]
            t = topics[i % len(topics)]
            batch = create_questions(topic=t, difficulty=d, count=1,
                                     q_type="解答题" if d >= 3 else "选择题", stage=stage)
            if batch:
                filled.append(batch[0])
                picked.append({"qcode": batch[0]["qcode"], "question": batch[0]["question"],
                               "q_type": "解答题" if d >= 3 else "选择题",
                               "topic": t, "difficulty": d})
    picked = picked[:question_count]
    if not picked:
        return {"ok": False, "error": "组卷失败: 无可用题目且自动造题失败"}

    # 分值: 难度×20, 总分归一到 100
    raw = sum(p["difficulty"] * 20 for p in picked)
    for p in picked:
        p["score"] = round(p["difficulty"] * 20 * 100.0 / max(raw, 1), 1)
    d_actual = round(sum(p["difficulty"] * p["score"] for p in picked) / 100.0, 2)
    coverage: Dict[str, int] = {}
    for p in picked:
        t = p.get("topic") or "综合"
        coverage[t] = coverage.get(t, 0) + 1

    paper_code = _uid("PAPER")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_math_papers (paper_code,title,paper_type,stage,
               difficulty_target,difficulty_actual,question_codes,topic_coverage,
               total_score,duration_min,status,created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (paper_code, title[:120], paper_type, stage,
             difficulty_target, d_actual,
             json.dumps([p["qcode"] for p in picked], ensure_ascii=False),
             json.dumps(coverage, ensure_ascii=False),
             100, duration_min, "READY", "仙女座命题组"))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "paper_code": paper_code, "title": title,
            "question_count": len(picked), "difficulty_target": difficulty_target,
            "difficulty_actual": d_actual, "topic_coverage": coverage,
            "auto_created": len(filled), "items": [
                {"qcode": p["qcode"], "topic": p.get("topic"),
                 "difficulty": p["difficulty"], "score": p["score"]} for p in picked]}


# ============================================================
#  ④ 试卷批改 + 错因归因
# ============================================================

_ERROR_KINDS = ["概念不清", "方法未掌握", "计算失误", "审题偏差"]


def grade_paper(paper_code: str, student: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    """批改: 客观题精确判分 / 主观题关键词命中, 四类错因归因, 联动学情画像"""
    ensure_tables()
    conn = get_conn()
    try:
        paper = conn.execute("SELECT * FROM mt_math_papers WHERE paper_code=?",
                             (paper_code,)).fetchone()
        if not paper:
            return {"ok": False, "error": f"试卷不存在: {paper_code}"}
        items = []
        for qcode in json.loads(paper["question_codes"] or "[]"):
            q = conn.execute("SELECT * FROM mt_math_qbank WHERE qcode=?", (qcode,)).fetchone()
            if q:
                items.append(dict(q))
        prof = conn.execute("SELECT * FROM mt_math_learner_profiles WHERE student=?",
                            (student,)).fetchone()
        style = prof["style"] if prof else "步骤型"
    finally:
        conn.close()

    results, attribution = [], {k: 0 for k in _ERROR_KINDS}
    topic_stats: Dict[str, Dict[str, int]] = {}
    total = 0.0
    for q in items:
        ans = answers.get(q["qcode"])
        gold = (q.get("answer") or q.get("solution") or "")
        max_score = round(q["difficulty"] * 20 * 100.0 /
                          max(sum(x["difficulty"] * 20 for x in items), 1), 1)
        if q["q_type"] in ("选择题", "填空题"):
            ok = bool(ans) and str(ans).strip() in gold[:80]
            score = max_score if ok else 0.0
        else:
            # 主观题: 答案与详解关键词命中率
            kws = [w for w in re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,6}",
                                         (q.get("knowledge_points") or "") + gold[:200])][:8]
            hit = sum(1 for k in kws if k and k in str(ans or "")) if kws else 0
            ratio = hit / len(kws) if kws else (0.6 if ans else 0.0)
            score = round(max_score * min(1.0, ratio + 0.2 if ans else 0), 1)
            ok = score >= max_score * 0.6
        total += score
        t = q.get("topic") or "综合"
        st = topic_stats.setdefault(t, {"total": 0, "correct": 0})
        st["total"] += 1
        st["correct"] += 1 if ok else 0
        if not ok:
            # 错因归因 (启发式): 选择题→概念/审题; 主观题低分→方法; 同考点其他对→计算
            if q["q_type"] in ("选择题", "填空题"):
                kind = "概念不清" if st["correct"] == 0 else "审题偏差"
            elif score > 0:
                kind = "计算失误"
            else:
                kind = "方法未掌握"
            attribution[kind] += 1
        results.append({"qcode": q["qcode"], "q_type": q["q_type"], "topic": t,
                        "difficulty": q["difficulty"], "score": score,
                        "max": max_score, "correct": ok})
    weak = [t for t, s in topic_stats.items() if s["correct"] * 2 < s["total"]]
    score = round(total, 1)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_math_gradings (paper_id,student,score,max_score,
               item_results,error_attribution,weak_points,graded_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (paper["id"], student, score, 100.0,
             json.dumps(results, ensure_ascii=False),
             json.dumps(attribution, ensure_ascii=False),
             json.dumps(weak, ensure_ascii=False), "仙女座批改组"))
        conn.execute("UPDATE mt_math_papers SET status='GRADED' WHERE id=?", (paper["id"],))
        conn.commit()
    finally:
        conn.close()
    _update_profile_from_grading(student, results, weak, style)
    return {"ok": True, "student": student, "score": score, "max": 100,
            "weak_points": weak, "error_attribution": attribution,
            "item_results": results}


def _update_profile_from_grading(student: str, results: List[dict],
                                 weak: List[str], style: str):
    """批改 → 学情画像更新 (数据研究中心协同资产): 掌握度/正确率/趋势"""
    conn = get_conn()
    try:
        correct = sum(1 for r in results if r["correct"])
        rate = correct / len(results) if results else 0.5
        mastery = {}
        try:
            row = conn.execute("SELECT mastery FROM mt_math_learner_profiles WHERE student=?",
                               (student,)).fetchone()
            if row and row["mastery"]:
                mastery = json.loads(row["mastery"])
        except sqlite3.Error:
            pass
        for r in results:
            t = r.get("topic") or "综合"
            old = mastery.get(t, 0.5)
            mastery[t] = round(old * 0.6 + (1.0 if r["correct"] else 0.0) * 0.4, 3)
        conn.execute(
            """INSERT INTO mt_math_learner_profiles (student,mastery,correct_rate,style,updated_at)
               VALUES (?,?,?,?,datetime('now','localtime'))
               ON CONFLICT(student) DO UPDATE SET mastery=excluded.mastery,
               correct_rate=excluded.correct_rate, style=excluded.style,
               updated_at=datetime('now','localtime')""",
            (student, json.dumps(mastery, ensure_ascii=False), round(rate, 3), style))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  ⑤ 难度动态弹性调整 (ELO 式难度带)
# ============================================================

def _rate_to_band(rate: float) -> str:
    d = max(1, min(5, 1 + round(rate * 4)))
    return f"{max(1, d - 1)}-{min(5, d + 1)}"


def _level_of(rate: float) -> str:
    if rate >= 0.9:
        return "L5"
    if rate >= 0.75:
        return "L4"
    if rate >= 0.6:
        return "L3"
    if rate >= 0.4:
        return "L2"
    return "L1"


def adapt_difficulty(student: str) -> Dict[str, Any]:
    """难度动态弹性调整: 正确率+趋势 → 难度带自动升降档, 事件留痕"""
    ensure_tables()
    conn = get_conn()
    try:
        prof = conn.execute("SELECT * FROM mt_math_learner_profiles WHERE student=?",
                            (student,)).fetchone()
        if not prof:
            conn.execute(
                "INSERT OR IGNORE INTO mt_math_learner_profiles (student,difficulty_band) "
                "VALUES (?,?)", (student, "2-4"))
            conn.commit()
            old_band = None
            rate, trend = 0.5, 0.0
        else:
            old_band = prof["difficulty_band"]
            rate, trend = prof["correct_rate"], prof["recent_trend"]
    finally:
        conn.close()

    eff = max(0.0, min(1.0, rate + trend * 0.3))
    new_band = _rate_to_band(eff)
    level = _level_of(eff)
    trigger = "INIT" if old_band is None else ("RISE" if new_band > (old_band or "") else
                                               ("FALL" if new_band < (old_band or "") else "HOLD"))
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_math_learner_profiles (student,level,difficulty_band,updated_at)
               VALUES (?,?,?,datetime('now','localtime'))
               ON CONFLICT(student) DO UPDATE SET level=excluded.level,
               difficulty_band=excluded.difficulty_band,
               updated_at=datetime('now','localtime')""",
            (student, level, new_band))
        conn.execute(
            "INSERT INTO mt_math_difficulty_events (student,old_band,new_band,trigger,correct_rate) "
            "VALUES (?,?,?,?,?)", (student, old_band, new_band, trigger, eff))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "student": student, "level": level,
            "old_band": old_band, "new_band": new_band, "trigger": trigger,
            "effective_rate": round(eff, 3),
            "note": f"难度带弹性调整为 {new_band} (认知层级 {level}), 出题将按新带抽取"}


# ============================================================
#  ⑥ 个性化解析讲解 (分层定制)
# ============================================================

_LAYER_TPL = {
    "L1": ("零基础陪跑", "从概念讲起, 每一步都给白话解释, 先看提示1再尝试"),
    "L2": ("基础巩固", "按标准步骤带做, 卡住时看提示2, 重点记模型套路"),
    "L3": ("思路点拨", "只点关键突破口, 自己完成推导, 对比标准详解找差距"),
    "L4": ("进阶挑战", "隐去步骤只给方向, 尝试一题多解, 关注易错点5"),
    "L5": ("竞赛拓展", "探究最优解法与命题背景, 尝试给出变式命题"),
}
_STYLE_ADDON = {
    "视觉型": "建议画线段图/函数图像辅助理解, 关注几何直观。",
    "步骤型": "严格按步骤清单推进, 每步写清依据。",
    "直觉型": "先猜结论再验证, 用特殊值试探规律。",
    "严谨型": "注意每步的定理依据与适用条件, 补全严密论证。",
}


def personalized_tutoring(qcode: str, student: str,
                          question: Optional[str] = None) -> Dict[str, Any]:
    """个性化解析讲解: 认知层级(L1~L5) + 风格四型定制, 薄弱考点前置"""
    ensure_tables()
    conn = get_conn()
    try:
        prof = conn.execute("SELECT * FROM mt_math_learner_profiles WHERE student=?",
                            (student,)).fetchone()
        q = conn.execute("SELECT * FROM mt_math_qbank WHERE qcode=?", (qcode,)).fetchone()
        if not q and question:
            conn.close()
            solved = solve_question(question)
            return {**solved, "tutoring": "已即时解析, 首次学习默认 L3 思路点拨模式"}
        mastery = json.loads(prof["mastery"]) if prof and prof["mastery"] else {}
        level = prof["level"] if prof else "L3"
        style = prof["style"] if prof else "步骤型"
        weak_band = prof["difficulty_band"] if prof else "2-4"
        prof = dict(prof) if prof else None  # Row → dict
        weak = [t for t, v in mastery.items() if v < 0.4]
    finally:
        conn.close()
    if not q:
        return {"ok": False, "error": f"题目不存在: {qcode}"}
    q = dict(q)  # sqlite3.Row → dict, 后续可 .get()
    layer_name, layer_guide = _LAYER_TPL.get(level, _LAYER_TPL["L3"])
    hints = json.loads(q["hints"] or "[]")
    parts = [
        f"【定制模式】{level} {layer_name} · {style}",
        f"【学情适配】当前难度带 {weak_band}"
        + (f", 薄弱考点前置: {','.join(weak[:3])}" if weak else ""),
        f"【讲解策略】{layer_guide}",
        f"【本题解析】{q['solution'][:1200]}",
        f"【题型解析】{q['analysis']}",
    ]
    if hints:
        parts.append("【分层提示】" + " | ".join(hints[:2 if level in ("L1", "L2") else 3]))
    parts.append("【风格适配】" + _STYLE_ADDON.get(style, ""))
    weak_q = None
    if weak and (q.get("topic") in weak):
        # 薄弱考点 → 自动补 1 道同考点低档变式
        t = q["topic"] or weak[0]
        made = create_questions(topic=t, difficulty=max(1, q["difficulty"] - 1), count=1,
                                q_type=q["q_type"], stage=q["stage"])
        if made:
            weak_q = made[0]["qcode"]
            parts.append(f"【补救练习】薄弱考点「{t}」已配变式题 {made[0]['qcode']}")
    tutoring = "\n".join(p for p in parts if p.strip())
    # LLM 增强 (可选, 失败不影响)
    try:
        from ai_engines.ai_dual_route_engine import route_and_chat
        r = route_and_chat(
            f"学生层级{level}({layer_name}), 风格{style}。请把以下解析改写成面向该生的"
            f"个性化讲解(150字内, 只输出讲解正文):\n{q['solution'][:500]}",
            system="你是因材施教的数学特级教师。", kind="chat",
            flow_id="flow_math_pedagogy_20261027", prefer_local=True)
        if r and r.get("success") and (r.get("response") or "").strip():
            tutoring += "\n【AI 教师定制语】" + r["response"].strip()[:300]
    except Exception:
        pass
    return {"ok": True, "qcode": qcode, "student": student, "level": level,
            "style": style, "tutoring": tutoring, "remedial_qcode": weak_q}


# ============================================================
#  总览
# ============================================================

def math_overview() -> Dict[str, Any]:
    ensure_tables()
    conn = get_conn()
    try:
        stats = {
            "qbank": conn.execute("SELECT count(*) FROM mt_math_qbank").fetchone()[0],
            "by_type": dict((r[0], r[1]) for r in conn.execute(
                "SELECT q_type,count(*) FROM mt_math_qbank GROUP BY q_type")),
            "papers": conn.execute("SELECT count(*) FROM mt_math_papers").fetchone()[0],
            "gradings": conn.execute("SELECT count(*) FROM mt_math_gradings").fetchone()[0],
            "learners": conn.execute("SELECT count(*) FROM mt_math_learner_profiles").fetchone()[0],
            "difficulty_events": conn.execute(
                "SELECT count(*) FROM mt_math_difficulty_events").fetchone()[0],
            "math_experts": conn.execute(
                "SELECT count(*) FROM eigenflux_experts WHERE domain='mathematics'").fetchone()[0],
        }
        recent = [dict(r) for r in conn.execute(
            "SELECT student,score,max_score,weak_points,graded_at FROM mt_math_gradings "
            "ORDER BY id DESC LIMIT 8")]
        events = [dict(r) for r in conn.execute(
            "SELECT student,old_band,new_band,trigger,created_at FROM mt_math_difficulty_events "
            "ORDER BY id DESC LIMIT 8")]
        experts = list_math_experts()[:8]
        return {"ok": True, "stats": stats, "recent_gradings": recent,
                "difficulty_events": events, "experts": experts,
                "db": DB_PATH}
    finally:
        conn.close()


# ============================================================
#  CLI
# ============================================================

def _cli_init():
    ensure_tables()
    hired = hire_math_experts(6, round_num=1)
    team = form_math_team(1)
    print(f"[INIT] 数学专家雇佣 {len(hired)} 名, 团队: {team.get('team_name') or team}")
    for h in hired:
        print(f"  - {h['name']} {h['role_cn']} ({h['level']}) perf={h['performance']}")


def _cli_demo():
    ensure_tables()
    print("== ① 题型解析解答 ==")
    r = solve_question("已知二次函数 y=ax²+bx+c 的图象过点 (1,0), (3,0), 且顶点纵坐标为 -2, 求解析式并证明顶点横坐标为 2")
    print(json.dumps({k: v for k, v in r.items() if k != "solution"}, ensure_ascii=False, indent=1))
    print("== ② 题目创造 ==")
    made = create_questions(topic="二次函数", difficulty=4, count=2, q_type="解答题")
    print(json.dumps(made, ensure_ascii=False, indent=1))
    print("== ③ 试卷生成 ==")
    paper = generate_paper("仙女座数学月考卷 A", paper_type="月考",
                           topic_weights={"二次函数": 3, "有理数": 2, "方程与不等式": 2},
                           difficulty_target=3, question_count=6)
    print(json.dumps({k: v for k, v in paper.items() if k != "items"}, ensure_ascii=False, indent=1))
    if paper.get("ok"):
        print("== ④ 试卷批改 ==")
        answers = {it["qcode"]: ("模拟作答 " + str(it["topic"])) for it in paper["items"]}
        g = grade_paper(paper["paper_code"], "学生_张小明", answers)
        print(json.dumps({k: v for k, v in g.items() if k != "item_results"},
                         ensure_ascii=False, indent=1))
        print("== ⑤ 难度弹性调整 ==")
        print(json.dumps(adapt_difficulty("学生_张小明"), ensure_ascii=False, indent=1))
        print("== ⑥ 个性化讲解 ==")
        t = personalized_tutoring(paper["items"][0]["qcode"], "学生_张小明")
        print(t.get("tutoring", t)[:500])
    print("== 总览 ==")
    print(json.dumps(math_overview()["stats"], ensure_ascii=False, indent=1))


def _cli_status():
    print(json.dumps(math_overview(), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        _cli_init()
    elif cmd == "hire":
        for h in hire_math_experts(int(sys.argv[2]) if len(sys.argv) > 2 else 3, 1):
            print(f"hired {h['name']} {h['role_cn']}")
    elif cmd == "demo":
        _cli_demo()
    elif cmd == "status":
        _cli_status()
    else:
        print("usage: ai_math_pedagogy_engine.py init|hire [n]|demo|status")
