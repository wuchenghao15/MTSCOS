#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学题型解析教学法 API (flow_math_pedagogy_20261027)
=====================================================
/api/math-pedagogy/* — 仙女座数学能力中枢对外服务层:
  GET  /overview  — 数学教学中枢总览 (题库/试卷/批改/学情/专家/难度事件)
  POST /solve     — 题型题库解析解答 (题型识别→母题匹配→三轨LLM→入库)
  POST /create    — 题目创造 (考点/难度/题型定向变式)
  POST /paper     — 试卷生成 (考点覆盖+难度分布约束+库存自动回填)
  POST /grade     — 试卷批改 (客观精确/主观关键词+四类错因归因+画像更新)
  POST /adapt     — 难度动态弹性调整 (ELO式难度带升降档)
  POST /tutor     — 个性化解析讲解 (L1~L5分层+风格四型定制)
  POST /hire      — EigenFlux 雇佣数学领域专家 (动态人力资源中心)
  POST /demo      — 全链路一键演示 (教学流水线自检)
"""
from flask import Blueprint, jsonify, request

from blueprints.chat_local_bp import _login_required
from blueprints.daemon_skill_lab_bp import _audit  # 统一审计 (flow_audit_20261020)
from engines.ai_math_pedagogy_engine import (
    ensure_tables, math_overview, solve_question, create_questions,
    generate_paper, grade_paper, adapt_difficulty, personalized_tutoring,
    hire_math_experts, form_math_team,
)

ai_math_pedagogy_bp = Blueprint("ai_math_pedagogy_bp", __name__)

_FLOW = "flow_math_pedagogy_20261027"


def _body():
    return request.get_json(silent=True) or {}


@ai_math_pedagogy_bp.route("/api/math-pedagogy/overview")
@_login_required
def mp_overview():
    try:
        return jsonify(math_overview())
    except Exception as e:
        _audit("edu", "MATH_OVERVIEW", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/solve", methods=["POST"])
@_login_required
def mp_solve():
    data = _body()
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "question 不能为空"}), 400
    try:
        r = solve_question(question, stage=data.get("stage") or "K12",
                           expert_specialty=data.get("expert_specialty") or "教法")
        _audit("edu", "MATH_SOLVE", question[:60],
               {"qcode": r.get("qcode"), "q_type": r.get("q_type"),
                "topic": r.get("topic"), "hit": r.get("hit")})
        return jsonify({"ok": True, **r})
    except Exception as e:
        _audit("edu", "MATH_SOLVE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/create", methods=["POST"])
@_login_required
def mp_create():
    data = _body()
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "topic 不能为空"}), 400
    try:
        made = create_questions(
            topic=topic, difficulty=int(data.get("difficulty") or 3),
            count=min(10, int(data.get("count") or 3)),
            q_type=data.get("q_type") or "解答题",
            stage=data.get("stage") or "K12",
            expert_specialty="命题")
        _audit("edu", "MATH_CREATE", topic,
               {"count": len(made), "difficulty": data.get("difficulty") or 3,
                "qcodes": [m["qcode"] for m in made]})
        return jsonify({"ok": True, "created": made})
    except Exception as e:
        _audit("edu", "MATH_CREATE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/paper", methods=["POST"])
@_login_required
def mp_paper():
    data = _body()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title 不能为空"}), 400
    try:
        r = generate_paper(
            title=title, paper_type=data.get("paper_type") or "月考",
            stage=data.get("stage") or "K12",
            topic_weights=data.get("topic_weights") or {},
            difficulty_target=int(data.get("difficulty_target") or 3),
            question_count=min(30, int(data.get("question_count") or 10)),
            duration_min=int(data.get("duration_min") or 90))
        _audit("edu", "MATH_PAPER", title[:60],
               {"paper_code": r.get("paper_code"), "question_count": r.get("question_count"),
                "difficulty_actual": r.get("difficulty_actual"),
                "auto_created": r.get("auto_created")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "MATH_PAPER", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/grade", methods=["POST"])
@_login_required
def mp_grade():
    data = _body()
    paper_code, student = (data.get("paper_code") or "").strip(), (data.get("student") or "").strip()
    if not paper_code or not student:
        return jsonify({"ok": False, "error": "paper_code/student 不能为空"}), 400
    try:
        r = grade_paper(paper_code, student, data.get("answers") or {})
        _audit("edu", "MATH_GRADE", f"{paper_code}/{student}",
               {"score": r.get("score"), "weak_points": r.get("weak_points"),
                "error_attribution": r.get("error_attribution")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "MATH_GRADE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/adapt", methods=["POST"])
@_login_required
def mp_adapt():
    data = _body()
    student = (data.get("student") or "").strip()
    if not student:
        return jsonify({"ok": False, "error": "student 不能为空"}), 400
    try:
        r = adapt_difficulty(student)
        _audit("edu", "MATH_ADAPT", student,
               {"old_band": r.get("old_band"), "new_band": r.get("new_band"),
                "trigger": r.get("trigger"), "level": r.get("level")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "MATH_ADAPT", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/tutor", methods=["POST"])
@_login_required
def mp_tutor():
    data = _body()
    student = (data.get("student") or "").strip()
    if not student:
        return jsonify({"ok": False, "error": "student 不能为空"}), 400
    try:
        r = personalized_tutoring((data.get("qcode") or "").strip(), student,
                                  question=(data.get("question") or "").strip() or None)
        _audit("edu", "MATH_TUTOR", f"{student}/{data.get('qcode') or 'inline'}",
               {"level": r.get("level"), "style": r.get("style"),
                "remedial_qcode": r.get("remedial_qcode")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "MATH_TUTOR", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/hire", methods=["POST"])
@_login_required
def mp_hire():
    """动态人力资源中心: 雇佣数学领域专家 + 组建数学教研团队 (跨中心)"""
    data = _body()
    count = min(20, int(data.get("count") or 3))
    try:
        hired = hire_math_experts(count, round_num=int(data.get("round") or 1))
        team = form_math_team(int(data.get("round") or 1)) if data.get("form_team", True) else None
        _audit("edu", "MATH_HIRE", f"mathematics×{count}",
               {"experts": [{"name": h["name"], "role_cn": h["role_cn"],
                             "level": h["level"]} for h in hired],
                "team": team})
        return jsonify({"ok": True, "hired": hired, "team": team})
    except Exception as e:
        _audit("edu", "MATH_HIRE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_math_pedagogy_bp.route("/api/math-pedagogy/demo", methods=["POST"])
@_login_required
def mp_demo():
    """全链路一键演示: 解析→造题→组卷→批改→弹性→讲解 (教学流水线自检)"""
    try:
        chain = {}
        chain["solve"] = solve_question(
            "已知二次函数 y=ax²+bx+c 的图象过点 (1,0), (3,0), 且顶点纵坐标为 -2, 求解析式并证明顶点横坐标为 2")
        chain["create"] = create_questions(topic="二次函数", difficulty=4, count=2, q_type="解答题")
        chain["paper"] = generate_paper(
            f"仙女座数学月考卷 {_FLOW[-8:]}", paper_type="月考",
            topic_weights={"二次函数": 3, "有理数": 2, "方程与不等式": 2},
            difficulty_target=3, question_count=6)
        if chain["paper"].get("ok"):
            answers = {it["qcode"]: f"模拟作答 {it['topic']}" for it in chain["paper"]["items"]}
            chain["grade"] = grade_paper(chain["paper"]["paper_code"], "学生_张小明", answers)
            chain["adapt"] = adapt_difficulty("学生_张小明")
            chain["tutor"] = personalized_tutoring(
                chain["paper"]["items"][0]["qcode"], "学生_张小明")
        _audit("edu", "MATH_DEMO", _FLOW,
               {k: ("ok" if isinstance(v, dict) and v.get("ok", True) else "done")
                for k, v in chain.items()})
        return jsonify({"ok": True, "chain": chain})
    except Exception as e:
        _audit("edu", "MATH_DEMO", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


# 模块导入即建表 (幂等, 与 ai_edu_academy_bp 同模式)
try:
    ensure_tables()
except Exception:
    pass
