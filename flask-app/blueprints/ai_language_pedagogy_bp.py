#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多语种在线教育平台 API (flow_lang_pedagogy_20261031)
=====================================================
/api/lang-platform/* — 仙女座多语种教学中枢对外服务层 (英/日/韩沉浸式学习):
  POST /auth/register            — 用户注册 (pbkdf2 + token)
  POST /auth/login               — 用户登录 (换发 token + 连续打卡)
  GET  /courses                  — 分级课程目录 (CEFR A1~C1, JLPT/TOPIK 标注)
  GET  /lesson/<code>            — 课时详情 (词汇/语法/口语/听力素材直出)
  GET  /vocab/due                — SRS 到期单词队列
  GET  /vocab/export             — 错词本导出 (JSON+CSV, 天团建议落地)
  GET  /daily-todo               — 每日任务清单 (四模块配额与完成度, 顾问建议落地)
  GET  /weekly-report            — 学习周报 (近7天模块趋势/打卡/XP, 顾问建议落地)
  POST /vocab/review             — 单词记忆复习 (SM-2 简化间隔重复)
  POST /grammar/practice         — 语法练习出题 (库存不足自动造题)
  POST /grammar/grade            — 练习批改 (五类错因归因 + 画像联动)
  POST /speaking/score           — 口语跟读评分 (本地相似度, 零 token)
  POST /listening/practice       — 听力训练 (先答后看原文判分)
  POST /test/generate            — 单元测验组卷
  GET  /progress                 — 学习进度追踪 (课程完成度/模块统计/打卡/XP)
  POST /path/recommend           — 个性化学习路径推荐 (薄弱点前置+每日计划)
  POST /tutor                    — 个性化解析讲解 (L1~L5 分层定制)
  POST /community/post           — 社区发帖 | GET /community/posts 列表
  POST /community/comment        — 社区评论 | POST /community/like 点赞
  GET  /achievements             — 成就墙 (徽章/XP/解锁状态)
  GET  /overview                 — 平台总览
  POST /hire                     — EigenFlux 雇佣 languages 领域专家
  POST /demo                     — 全链路一键演示 (平台自检)

鉴权: 请求头 X-Lang-Token (注册/登录返回) 优先; 缺省回落会话用户 (_login_required)。
"""
from flask import Blueprint, jsonify, request

from blueprints.chat_local_bp import _login_required
from blueprints.daemon_skill_lab_bp import _audit  # 统一审计 (flow_audit_20261020)
from engines.ai_language_pedagogy_engine import (
    ensure_tables, seed_base_assets, register_user, login_user, auth_user,
    list_courses, get_lesson_detail, due_vocab, review_vocab,
    grammar_practice, grade_submission, score_speaking, listening_practice,
    generate_unit_test, get_progress, recommend_path, personalized_explain,
    create_post, list_posts, comment_post, like_post, list_achievements,
    platform_overview, hire_language_experts, form_language_team,
    solve_language_question, create_questions, adapt_difficulty,
)

ai_language_pedagogy_bp = Blueprint("ai_language_pedagogy_bp", __name__)

_FLOW = "flow_lang_pedagogy_20261031"


def _body():
    return request.get_json(silent=True) or {}


def _lang(v) -> str:
    v = (v or "en").lower()
    return v if v in ("en", "ja", "ko") else "en"


def _actor() -> dict:
    """鉴权: X-Lang-Token (或 body.token) 优先 → X-Session-User 会话名回落"""
    tok = request.headers.get("X-Lang-Token") or ""
    if not tok and request.is_json:
        tok = (request.get_json(silent=True) or {}).get("token") or ""
    sess = request.headers.get("X-Session-User") or ""
    u = auth_user(token=tok or "", username=sess or "")
    if u:
        return {"ok": True, "username": u["username"], "display_name": u.get("display_name"),
                "xp": u.get("xp"), "level": u.get("level"), "streak_days": u.get("streak_days")}
    return {"ok": False, "error": "未登录: 请先注册/登录获取 X-Lang-Token"}


@ai_language_pedagogy_bp.route("/api/lang-platform/auth/register", methods=["POST"])
def lp_register():
    data = _body()
    r = register_user((data.get("username") or "").strip(),
                      data.get("password") or "",
                      (data.get("display_name") or "").strip(),
                      data.get("target_languages") or "en,ja,ko")
    if r.get("ok"):
        _audit("edu", "LANG_REGISTER", r["username"], {"display_name": r.get("display_name")})
        return jsonify(r)
    return jsonify(r), 400


@ai_language_pedagogy_bp.route("/api/lang-platform/auth/login", methods=["POST"])
def lp_login():
    data = _body()
    r = login_user((data.get("username") or "").strip(), data.get("password") or "")
    if r.get("ok"):
        _audit("edu", "LANG_LOGIN", r["username"], {"streak": r.get("streak_days")})
        return jsonify(r)
    return jsonify(r), 401


@ai_language_pedagogy_bp.route("/api/lang-platform/courses")
@_login_required
def lp_courses():
    return jsonify({"ok": True, "courses": list_courses(_lang(request.args.get("language")))})


@ai_language_pedagogy_bp.route("/api/lang-platform/lesson/<lesson_code>")
@_login_required
def lp_lesson(lesson_code):
    try:
        return jsonify(get_lesson_detail(lesson_code))
    except Exception as e:
        _audit("edu", "LANG_LESSON", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/vocab/due")
@_login_required
def lp_vocab_due():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    return jsonify({"ok": True, "words": due_vocab(
        actor["username"], _lang(request.args.get("language")),
        min(50, int(request.args.get("limit") or 10)))})


@ai_language_pedagogy_bp.route("/api/lang-platform/vocab/review", methods=["POST"])
@_login_required
def lp_vocab_review():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    if not (data.get("word_id") or "").strip():
        return jsonify({"ok": False, "error": "word_id 不能为空"}), 400
    try:
        r = review_vocab(actor["username"], data["word_id"].strip(),
                         "good" if data.get("result", "good") == "good" else "miss")
        _audit("edu", "LANG_VOCAB", actor["username"],
               {"word_id": data["word_id"], "result": data.get("result", "good"),
                "achievements": [a["code"] for a in r.get("new_achievements", [])]})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_VOCAB", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/grammar/practice", methods=["POST"])
@_login_required
def lp_grammar_practice():
    data = _body()
    try:
        r = grammar_practice(_lang(data.get("language")), (data.get("topic") or "").strip(),
                             int(data.get("difficulty") or 0),
                             min(20, int(data.get("count") or 5)))
        _audit("edu", "LANG_GRAMMAR_PRACTICE", data.get("language") or "en",
               {"count": r.get("count"), "topic": data.get("topic")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_GRAMMAR_PRACTICE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/grammar/grade", methods=["POST"])
@_login_required
def lp_grammar_grade():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    answers = data.get("answers") or {}
    if not isinstance(answers, dict) or not answers:
        return jsonify({"ok": False, "error": "answers 需为 {qcode: 作答} 字典"}), 400
    try:
        r = grade_submission((data.get("paper_code") or "").strip(), actor["username"], answers)
        _audit("edu", "LANG_GRADE", actor["username"],
               {"score": r.get("score"), "weak_points": r.get("weak_points"),
                "error_attribution": r.get("error_attribution")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_GRADE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/speaking/score", methods=["POST"])
@_login_required
def lp_speaking():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    if not (data.get("sp_id") or "").strip():
        return jsonify({"ok": False, "error": "sp_id 不能为空"}), 400
    try:
        r = score_speaking(actor["username"], data["sp_id"].strip(), data.get("said") or "")
        _audit("edu", "LANG_SPEAKING", actor["username"],
               {"sp_id": data["sp_id"], "score": r.get("score")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_SPEAKING", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/listening/practice", methods=["POST"])
@_login_required
def lp_listening():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    if not (data.get("audio_id") or "").strip():
        return jsonify({"ok": False, "error": "audio_id 不能为空"}), 400
    try:
        r = listening_practice(actor["username"], data["audio_id"].strip(),
                               data.get("answers") or {})
        _audit("edu", "LANG_LISTENING", actor["username"],
               {"audio_id": data["audio_id"], "score": r.get("score")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_LISTENING", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/test/generate", methods=["POST"])
@_login_required
def lp_test():
    data = _body()
    try:
        r = generate_unit_test(_lang(data.get("language")),
                               (data.get("cefr") or "A1").upper(),
                               (data.get("title") or "").strip(),
                               min(20, int(data.get("question_count") or 6)),
                               data.get("topics"))
        _audit("edu", "LANG_TEST", data.get("language") or "en",
               {"paper_code": r.get("paper_code"), "count": r.get("question_count"),
                "auto_created": r.get("auto_created")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_TEST", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/progress")
@_login_required
def lp_progress():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    try:
        return jsonify(get_progress(actor["username"],
                                    _lang(request.args.get("language") or "")))
    except Exception as e:
        _audit("edu", "LANG_PROGRESS", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/vocab/export")
@_login_required
def lp_vocab_export():
    """错词本导出 (天团建议落地): SRS 答错词+到期词, JSON+CSV 一键带走"""
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    try:
        from engines.ai_language_pedagogy_engine import export_mistake_words
        return jsonify(export_mistake_words(actor["username"],
                                            _lang(request.args.get("language") or "")))
    except Exception as e:
        _audit("edu", "LANG_VOCAB_EXPORT", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/daily-todo")
@_login_required
def lp_daily_todo():
    """每日任务清单 (顾问建议落地): 四模块今日配额与完成度"""
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    try:
        from engines.ai_language_pedagogy_engine import daily_todo
        return jsonify(daily_todo(actor["username"],
                                  _lang(request.args.get("language"))))
    except Exception as e:
        _audit("edu", "LANG_DAILY_TODO", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/weekly-report")
@_login_required
def lp_weekly_report():
    """学习周报 (顾问建议落地): 近 7 天模块练习量/得分趋势/打卡/XP"""
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    try:
        from engines.ai_language_pedagogy_engine import weekly_report
        return jsonify(weekly_report(actor["username"]))
    except Exception as e:
        _audit("edu", "LANG_WEEKLY", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/path/recommend", methods=["POST"])
@_login_required
def lp_path():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    try:
        r = recommend_path(actor["username"], _lang(data.get("language")))
        _audit("edu", "LANG_PATH", actor["username"],
               {"language": r.get("language"), "level": r.get("level"),
                "weak_points": r.get("weak_points")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_PATH", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/tutor", methods=["POST"])
@_login_required
def lp_tutor():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    try:
        r = personalized_explain((data.get("qcode") or "").strip(), actor["username"],
                                 question=(data.get("question") or "").strip() or None)
        _audit("edu", "LANG_TUTOR", actor["username"],
               {"qcode": data.get("qcode"), "level": r.get("level"),
                "remedial_qcode": r.get("remedial_qcode")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_TUTOR", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/community/post", methods=["POST"])
@_login_required
def lp_post():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    try:
        r = create_post(actor["username"], _lang(data.get("language")),
                        data.get("title") or "", data.get("content") or "")
        if r.get("ok"):
            _audit("edu", "LANG_POST", actor["username"], {"post_id": r.get("post_id")})
            return jsonify(r)
        return jsonify(r), 400
    except Exception as e:
        _audit("edu", "LANG_POST", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/community/posts")
@_login_required
def lp_posts():
    return jsonify({"ok": True, "posts": list_posts(
        _lang(request.args.get("language") or ""),
        min(100, int(request.args.get("limit") or 20)))})


@ai_language_pedagogy_bp.route("/api/lang-platform/community/comment", methods=["POST"])
@_login_required
def lp_comment():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    try:
        r = comment_post(actor["username"], (data.get("post_id") or "").strip(),
                         data.get("content") or "")
        if r.get("ok"):
            _audit("edu", "LANG_COMMENT", actor["username"], {"post_id": data.get("post_id")})
            return jsonify(r)
        return jsonify(r), 400
    except Exception as e:
        _audit("edu", "LANG_COMMENT", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/community/like", methods=["POST"])
@_login_required
def lp_like():
    actor = _actor()
    if not actor["ok"]:
        return jsonify(actor), 401
    data = _body()
    try:
        r = like_post(actor["username"], (data.get("post_id") or "").strip())
        if r.get("ok"):
            return jsonify(r)
        return jsonify(r), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/achievements")
@_login_required
def lp_achievements():
    actor = _actor()
    return jsonify(list_achievements(actor.get("username") if actor.get("ok") else ""))


@ai_language_pedagogy_bp.route("/api/lang-platform/overview")
@_login_required
def lp_overview():
    try:
        return jsonify(platform_overview())
    except Exception as e:
        _audit("edu", "LANG_OVERVIEW", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/hire", methods=["POST"])
@_login_required
def lp_hire():
    """动态人力资源中心: 雇佣 languages 领域专家 + 组建多语种教研团队 (跨中心)"""
    data = _body()
    count = min(20, int(data.get("count") or 3))
    try:
        hired = hire_language_experts(count, round_num=int(data.get("round") or 1))
        team = form_language_team(int(data.get("round") or 1)) if data.get("form_team", True) else None
        _audit("edu", "LANG_HIRE", f"languages×{count}",
               {"experts": [{"name": h["name"], "role_cn": h["role_cn"], "level": h["level"]}
                            for h in hired], "team": team})
        return jsonify({"ok": True, "hired": hired, "team": team})
    except Exception as e:
        _audit("edu", "LANG_HIRE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/demo", methods=["POST"])
@_login_required
def lp_demo():
    """全链路一键演示: 注册→解析→造题→组卷→四模块→批改→弹性→路径→社区→成就"""
    try:
        import engines.ai_language_pedagogy_engine as eng
        uname = f"apide_{eng._uid('U')[-6:]}"
        chain = {}
        chain["register"] = {k: v for k, v in
                             eng.register_user(uname, "demo123456", "API演示学员").items()
                             if k != "token"}
        chain["solve"] = {k: v for k, v in eng.solve_language_question(
            "「て形」的语法点: ちょっと待って___ください, 助词怎么用? (日语)", "ja").items()
            if k != "solution"}
        chain["create"] = eng.create_questions(topic="て形", language="ja", difficulty=2,
                                               count=2, q_type="语法选择")
        chain["unit_test"] = {k: v for k, v in eng.generate_unit_test(
            "ja", "A2", question_count=5).items() if k != "items"}
        words = eng.due_vocab(uname, "ja", limit=2)
        chain["vocab_srs"] = eng.review_vocab(uname, words[0]["word_id"], "good") if words else {"ok": False}
        sp_rows = eng.get_lesson_detail("JA-N5-L3")
        sp_id = (sp_rows.get("materials", {}).get("speaking") or [{}])[0].get("sp_id")
        if sp_id:
            s = eng.score_speaking(uname, sp_id, "はじめまして、どうぞよろしくお願いします")
            chain["speaking"] = {"score": s.get("score"), "feedback": s.get("feedback")}
        if chain["unit_test"].get("ok"):
            paper = eng.generate_unit_test("ja", "A2", question_count=4)
            if paper.get("ok"):
                answers = {it["qcode"]: f"模拟作答 {it['topic']}" for it in paper["items"]}
                g = eng.grade_submission(paper["paper_code"], uname, answers)
                chain["grade"] = {"score": g.get("score"), "weak_points": g.get("weak_points"),
                                  "error_attribution": g.get("error_attribution")}
                chain["adapt"] = eng.adapt_difficulty(uname, "ja")
        chain["path"] = {k: eng.recommend_path(uname, "ja").get(k)
                         for k in ("level", "layer", "weak_points", "next_lessons")}
        chain["community"] = eng.create_post(uname, "ja", "跟读打卡第 1 天",
                                             "今天开始影子跟读, 一起加油!")
        ach = eng.list_achievements(uname)
        chain["achievements"] = {"earned_count": ach["earned_count"],
                                 "earned": [a["name"] for a in ach["achievements"] if a["earned"]]}
        chain["progress"] = eng.get_progress(uname, "ja")
        _audit("edu", "LANG_DEMO", _FLOW,
               {k: ("ok" if isinstance(v, dict) and v.get("ok", True) else "done")
                for k, v in chain.items()})
        return jsonify({"ok": True, "demo_user": uname, "chain": chain})
    except Exception as e:
        _audit("edu", "LANG_DEMO", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


# ── 组织对齐与巡逻防控 (flow_lang_org_20261031) — 管理端点, 不入学习者白名单, 海关守卫管控 ──

@ai_language_pedagogy_bp.route("/api/lang-platform/org/overview")
@_login_required
def lp_org_overview():
    try:
        from engines.ai_language_org_alignment_engine import org_overview
        return jsonify(org_overview())
    except Exception as e:
        _audit("edu", "LANG_ORG_OVERVIEW", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/org/patrol", methods=["POST"])
@_login_required
def lp_org_patrol():
    """触发一轮维护部队七检巡逻 (资产/库存/API/留痕/专家/守卫/活跃)"""
    try:
        from engines.ai_language_org_alignment_engine import patrol_once
        r = patrol_once()
        _audit("edu", "LANG_PATROL", _FLOW, {"summary": r.get("summary"),
                                             "maintenance_fed": r.get("maintenance_fed")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_PATROL", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/org/committee", methods=["POST"])
@_login_required
def lp_org_committee():
    """触发语言教学专家委员会评审 (EigenFlux chief+expert×2)"""
    try:
        from engines.ai_language_org_alignment_engine import committee_review
        r = committee_review()
        _audit("edu", "LANG_COMMITTEE", _FLOW,
               {"verdict": r.get("verdict"), "total": r.get("total")})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_COMMITTEE", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_language_pedagogy_bp.route("/api/lang-platform/org/consult", methods=["POST"])
@_login_required
def lp_org_consult():
    """触发教授/顾问/天团三方会诊"""
    try:
        from engines.ai_language_org_alignment_engine import advisor_consult
        r = advisor_consult()
        _audit("edu", "LANG_CONSULT", _FLOW, {"roles": [c["role"] for c in r.get("consults", [])]})
        return jsonify(r)
    except Exception as e:
        _audit("edu", "LANG_CONSULT", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


# 模块导入即建表 (幂等, 与 ai_math_pedagogy_bp 同模式)
try:
    ensure_tables()
except Exception:
    pass
