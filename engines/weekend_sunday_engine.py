#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gobelin 周末周日引擎 — 考试 → 晋升 → 淘汰 → 再培训
====================================================

4 阶段:
  S1 员工考试      从 mtscos_ai_employees + mt_skill_registry 生成考题 → Ollama 判分 → mt_lab_hr_log
  S2 晋升/淘汰决策 exam_score >= 85 晋升, <50 淘汰, 50-85 留队再培训 → 更新 mtscos_ai_employees.scores_json
  S3 再培训计划    → mt_center_direction_pool / mt_ai_auto_hire_log → mt_center_evolution_log(WEEKLY_TRAINING_ASSIGNED)
  S4 总结 & 投喂 AI  统计报告 → mt_center_knowledge_points(kp_type='weekly_hr') → mt_fm_brain_feed → mt_center_knowledge_digest

CLI:
  python3 weekend_sunday_engine.py dry    # 干跑, 不写库, 用 mock 分
  python3 weekend_sunday_engine.py run    # 真跑, 调 Ollama

模型: qwen2.5:3b (若不可用则降级为规则打分)

FLOW_ID: flow_gobelin_weekend_sun_20261108
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import sqlite3
import urllib.request
import urllib.error
import socket
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径解析 ──
_ENGINES_DIR = Path(__file__).resolve().parent
_FLASK_APP_DIR = _ENGINES_DIR.parent
_PROJECT_ROOT = _FLASK_APP_DIR.parent

try:
    from engines._common.db_resolver import get_app_db
    DB_PATH = get_app_db()
except Exception:
    DB_PATH = str(_FLASK_APP_DIR / "database" / "app.db")

REPORT_DIR = _PROJECT_ROOT / "_runtime"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

FLOW_ID = "flow_gobelin_weekend_sun_20261108"
DRY_RUN = False

# ── 长假特殊模式 (由 holiday_trigger_engine.py 传入) ──
HOLIDAY_LAST = None     # 长假最后一天模式: 假期名称
HOLIDAY_WEEKEND = None  # 长假中间周末模式: 假期名称
POST_TRADE_DATE = None  # 节后第一个交易日 (YYYY-MM-DD)

# Ollama
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("WEEKEND_EXAM_MODEL", "qwen2.5:3b")


# ══════════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════════
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:10]


def _exec(conn: sqlite3.Connection, sql: str, params=(), desc: str = "") -> None:
    if DRY_RUN:
        print(f"  [DRY] {desc or sql[:80]}")
        return
    conn.execute(sql, params)


# ══════════════════════════════════════════════════════════════════
# Ollama 调用
# ══════════════════════════════════════════════════════════════════
def ollama_generate(prompt: str, model: str = None) -> str | None:
    """调 Ollama 生成文本, 失败返回 None"""
    url = f"{OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(30)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                return body.get("response", "")
        finally:
            socket.setdefaulttimeout(old_timeout)
    except Exception as e:
        print(f"  [Ollama] fail: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# S1. 员工考试
# ══════════════════════════════════════════════════════════════════
def s1_employee_exam(conn: sqlite3.Connection) -> list[dict]:
    print("=" * 60)
    print("S1. 员工考试")
    print("=" * 60)

    # 取活跃员工 (兼容 status 大小写)
    employees = conn.execute(
        "SELECT id, uid, name, role, dept, expertise_json, skills_json, scores_json "
        "FROM mtscos_ai_employees WHERE is_active=1 AND UPPER(status)='ACTIVE'"
    ).fetchall()
    print(f"  活跃员工: {len(employees)}")

    # 从 evolution_log 取近 7 天的实际场景
    scenes = conn.execute(
        "SELECT event, detail, created_at FROM mt_center_evolution_log "
        "WHERE created_at >= datetime('now','-7 days') ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    scene_texts = [f"{e}: {(d or '')[:200]}" for e, d, _ in scenes]
    if not scene_texts:
        scene_texts = ["常规巡检", "模型升级", "数据校准", "风控检查"]
    print(f"  可用场景: {len(scene_texts)} 条")

    # 取技能清单
    skills = conn.execute(
        "SELECT skill_id, skill_name, category FROM mt_skill_registry WHERE readiness=1 LIMIT 50"
    ).fetchall()
    print(f"  可用技能: {len(skills)} 项")

    exam_results = []

    for emp in employees:
        emp_id, uid, name, role, dept, expertise_json, skills_json, scores_json = emp
        try:
            expertise = json.loads(expertise_json) if expertise_json else []
        except Exception:
            expertise = []
        try:
            existing_scores = json.loads(scores_json) if scores_json else {}
        except Exception:
            existing_scores = {}

        expertise_str = ", ".join(expertise) if isinstance(expertise, list) else str(expertise)

        # 生成 5 道题 — 从场景 + 员工领域匹配
        import random
        random.seed(hash(name) & 0xFFFF)
        chosen_scenes = random.sample(scene_texts, min(5, len(scene_texts)))

        questions = []
        for i, scene in enumerate(chosen_scenes):
            questions.append(
                f"Q{i+1} 场景: {scene}\n"
                f"作为 {name} ({dept}/{role}), 你会如何响应? 请输出合理 JSON"
            )

        full_prompt = (
            f"你是一名严格的 HR 考官。下面是 {name} (领域: {expertise_str}) 的 5 道实战场景题。\n"
            f"每题请给出一个 0-100 的分数, 评分维度: 响应质量 / 知识覆盖 / 决策合理性。\n"
            f"最终输出一个 JSON: {{\"scores\": [s1,s2,s3,s4,s5], \"average\": avg, \"feedback\": \"...\"}}\n\n"
            + "\n\n".join(questions)
            + "\n\n请直接输出 JSON, 不要解释。"
        )

        score = None
        ollama_used = False

        if DRY_RUN:
            # dry-run 用模拟分
            score = 60 + (hash(name) % 30)  # 60-89
            feedback = "[DRY] 模拟分"
        else:
            response = ollama_generate(full_prompt)
            if response:
                ollama_used = True
                # 尝试从 response 提取 JSON
                try:
                    # 找第一个 { 到最后一个 }
                    s = response.index("{")
                    e = response.rindex("}") + 1
                    parsed = json.loads(response[s:e])
                    scores_list = parsed.get("scores", [])
                    avg = parsed.get("average", (sum(scores_list) / len(scores_list)) if scores_list else None)
                    if avg is not None:
                        score = int(float(avg))
                        feedback = parsed.get("feedback", "")[:200]
                    else:
                        score = int(sum(scores_list) / len(scores_list)) if scores_list else 70
                        feedback = "[Ollama 无 average 字段]"
                except Exception:
                    # 退化: 找数字
                    import re
                    nums = re.findall(r"\b(\d{2,3})\b", response)
                    valid_nums = [int(n) for n in nums if 30 <= int(n) <= 100]
                    score = valid_nums[0] if valid_nums else 70
                    feedback = "[Ollama JSON 解析失败]"
            else:
                # Ollama 不可用 → 规则打分 (保守)
                score = existing_scores.get("last_exam_score", 70)
                feedback = "[Ollama 不可用, 规则回退, 使用上次分数]"

        score = max(0, min(100, int(score)))

        result = {
            "employee_id": emp_id,
            "uid": uid,
            "name": name,
            "role": role,
            "dept": dept,
            "exam_score": score,
            "ollama_used": ollama_used,
            "feedback": feedback,
            "existing_scores": existing_scores,
        }
        exam_results.append(result)

        # 写 mt_lab_hr_log
        _exec(
            conn,
            "INSERT INTO mt_lab_hr_log (employee_name, employee_code, role, action, verdict, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                name,
                uid,
                role or "employee",
                "WEEKLY_EXAM",
                f"score={score}, ollama={'1' if ollama_used else '0'}",
                _now(),
            ),
            desc=f"S1 HR log for {name}",
        )

        print(f"  {name:20s} → score={score:3d}  ollama={'✓' if ollama_used else '✗'}")

    return exam_results


# ══════════════════════════════════════════════════════════════════
# S2. 晋升/淘汰决策
# ══════════════════════════════════════════════════════════════════
def s2_promote_eliminate(conn: sqlite3.Connection, exam_results: list[dict]) -> list[dict]:
    print("\n" + "=" * 60)
    print("S2. 晋升 / 淘汰 决策")
    print("=" * 60)

    decisions = []
    for er in exam_results:
        score = er["exam_score"]
        existing = er["existing_scores"]

        promotions = existing.get("promotions", 0)
        eliminations = existing.get("eliminations", 0)
        trend = existing.get("trend", [])
        trend.append(score)
        trend = trend[-5:]  # 保留最近 5 周
        last_eliminated_week = existing.get("last_eliminated_week", 0)
        level = existing.get("level", 1)
        consecutive_low = existing.get("consecutive_low", 0)

        action_taken = "KEEP"
        status = "KEEP"
        new_level = level

        if score >= 85:
            # 晋升
            promotions += 1
            level += 1
            new_level = level
            action_taken = "PROMOTED"
            status = "PROMOTED"
            consecutive_low = 0
            print(f"  ⬆️ {er['name']} 晋升 level {level}")
        elif score < 50:
            consecutive_low += 1
            if consecutive_low >= 2:
                action_taken = "ELIMINATED"
                status = "ELIMINATED"
                eliminations += 1
                print(f"  ⛔ {er['name']} 淘汰 (连续 {consecutive_low} 周 < 50)")
            else:
                action_taken = "NEEDS_RETRAIN"
                status = "NEEDS_RETRAIN"
                print(f"  ⚠️ {er['name']} 低分 需再培训 ({consecutive_low}/2)")
        else:  # 50-84
            action_taken = "NEEDS_RETRAIN"
            status = "NEEDS_RETRAIN"
            if score >= 75:
                consecutive_low = 0
            print(f"  📚 {er['name']} 留队, 需再培训 (score={score})")

        new_scores_json = {
            **existing,
            "last_exam_score": score,
            "trend": trend,
            "promotions": promotions,
            "eliminations": eliminations,
            "consecutive_low": consecutive_low,
            "level": new_level,
            "last_exam_date": _now(),
            "last_action": action_taken,
        }

        # 更新 mtscos_ai_employees
        if action_taken == "ELIMINATED":
            _exec(
                conn,
                "UPDATE mtscos_ai_employees SET scores_json=?, status='ELIMINATED', updated_at=? WHERE id=?",
                (json.dumps(new_scores_json, ensure_ascii=False), _now(), er["employee_id"]),
                desc=f"S2 ELIMINATE {er['name']}",
            )
        else:
            _exec(
                conn,
                "UPDATE mtscos_ai_employees SET scores_json=?, updated_at=? WHERE id=?",
                (json.dumps(new_scores_json, ensure_ascii=False), _now(), er["employee_id"]),
                desc=f"S2 UPDATE scores {er['name']}",
            )

        # 淘汰写入 HR log
        if action_taken == "ELIMINATED":
            _exec(
                conn,
                "INSERT INTO mt_lab_hr_log (employee_name, employee_code, role, action, verdict, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (er["name"], er["uid"], er["role"], "ELIMINATED", f"score={score}, consecutive_low={consecutive_low}", _now()),
                desc=f"S2 HR log ELIMINATED {er['name']}",
            )

        decisions.append({**er, "action_taken": action_taken, "status": status, "new_level": new_level})

    return decisions


# ══════════════════════════════════════════════════════════════════
# S3. 再培训计划
# ══════════════════════════════════════════════════════════════════
def s3_retrain_plan(conn: sqlite3.Connection, decisions: list[dict]) -> dict:
    print("\n" + "=" * 60)
    print("S3. 再培训计划")
    print("=" * 60)

    retrain_count = 0
    rehire_count = 0

    # 低分技能匹配 (从 mt_skill_registry 按 category 分配)
    low_score_skills = conn.execute(
        "SELECT skill_id, skill_name, category FROM mt_skill_registry WHERE readiness=1 "
    ).fetchall()
    skill_pool = {(s[0], s[1]): s[2] for s in low_score_skills}

    for d in decisions:
        name = d["name"]
        score = d["exam_score"]
        action = d["action_taken"]

        if action == "NEEDS_RETRAIN":
            retrain_count += 1
            # 匹配缺失技能 → 取 score/5 个作为训练方向
            import random
            random.seed(hash(name + "retrain") & 0xFFFF)
            chosen_skills = random.sample(list(skill_pool.keys()), min(3, len(skill_pool)))
            skill_names = [s[1] for s in chosen_skills]

            direction_title = f"WEEKLY_RETRAIN_EMPLOYEE_{name}"
            seed_text = (
                f"员工 {name} 本周考试 {score} 分, 需加强技能: {', '.join(skill_names)}。"
                f"重点提升领域: {d.get('dept', '')} / {d.get('role', '')}"
            )

            _exec(
                conn,
                "INSERT OR IGNORE INTO mt_center_direction_pool "
                "(center_name, direction_title, seed, status, priority, auto_spawned) "
                "VALUES (?,?,?,?,?,?)",
                ("hr_center", direction_title, seed_text, "SEED", max(5, (100 - score) // 5), 1),
                desc=f"S3 retrain direction {name}",
            )

        elif action == "ELIMINATED":
            rehire_count += 1
            # 触发 auto_hire
            hire_id = "HIRE-" + _short_uuid()
            hire_type = "WEEKLY_REPLACEMENT"
            hire_name = f"{name.replace('员', '').replace('师', '')}_replacement_{_short_uuid()[:4]}"
            role = d.get("role", "employee")

            _exec(
                conn,
                "INSERT INTO mt_ai_auto_hire_log (hire_id, hire_type, employee_name, employee_role, source, details_json, hired_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    hire_id,
                    hire_type,
                    hire_name,
                    role,
                    "weekend_sunday_engine",
                    json.dumps({"replaces": name, "reason": "weekly exam elimination"}, ensure_ascii=False),
                    _now(),
                ),
                desc=f"S3 auto_hire for eliminated {name}",
            )

    print(f"  再培训: {retrain_count} 人")
    print(f"  淘汰 → 重新招聘: {rehire_count} 人")

    _exec(
        conn,
        "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
        (
            "hr_center",
            "WEEKLY_TRAINING_ASSIGNED",
            json.dumps({"retrain": retrain_count, "rehire": rehire_count}, ensure_ascii=False),
        ),
        desc="S3 evolution_log WEEKLY_TRAINING_ASSIGNED",
    )

    return {"retrain": retrain_count, "rehire": rehire_count}


# ══════════════════════════════════════════════════════════════════
# S4. 总结 & 投喂 AI
# ══════════════════════════════════════════════════════════════════
def s4_summary_and_feed(conn: sqlite3.Connection, decisions: list[dict], retrain_stat: dict) -> None:
    print("\n" + "=" * 60)
    print("S4. 总结 & 投喂 AI")
    print("=" * 60)

    scores = [d["exam_score"] for d in decisions]
    promotions = [d for d in decisions if d["action_taken"] == "PROMOTED"]
    eliminated = [d for d in decisions if d["action_taken"] == "ELIMINATED"]
    need_retrain = [d for d in decisions if d["action_taken"] == "NEEDS_RETRAIN"]

    avg_score = sum(scores) / len(scores) if scores else 0
    report = {
        "generated_at": _now(),
        "flow_id": FLOW_ID,
        "exam_stats": {
            "total_employees": len(decisions),
            "avg_score": round(avg_score, 2),
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "ollama_used_count": sum(1 for d in decisions if d["ollama_used"]),
        },
        "promotions": [{"name": d["name"], "score": d["exam_score"], "new_level": d["new_level"]} for d in promotions],
        "eliminations": [{"name": d["name"], "score": d["exam_score"]} for d in eliminated],
        "retrain_count": len(need_retrain),
        "retrain_stat": retrain_stat,
    }

    print(f"  考试统计: 平均分 {avg_score:.1f}  晋升 {len(promotions)}  淘汰 {len(eliminated)}  再培训 {len(need_retrain)}")

    # 写 knowledge_points (weekly_hr)
    summary_text = (
        f"周日 HR 考试: {len(decisions)} 员工, 平均分 {avg_score:.1f}, "
        f"晋升 {len(promotions)}, 淘汰 {len(eliminated)}, 再培训 {len(need_retrain)}"
    )
    _exec(
        conn,
        "INSERT OR IGNORE INTO mt_center_knowledge_points "
        "(center_name, kp_type, knowledge_title, knowledge_body, confidence) "
        "VALUES (?,?,?,?,?)",
        (
            "hr_center",
            "weekly_hr",
            f"周日HR考试_{datetime.now().strftime('%Y%m%d')}",
            json.dumps(report, ensure_ascii=False)[:4000],
            0.85,
        ),
        desc="S4 knowledge_points weekly_hr",
    )

    # 写 brain_feed
    feed_entries = []
    for d in promotions:
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SUNDAY_EXAM",
                "category": "PROMOTION",
                "asr_text": f"员工 {d['name']} 晋升, 考试分 {d['exam_score']}",
                "trigger_keywords": "晋升,优秀员工,周末考试",
                "emotion": "HAWK",
                "emotion_score": 0.9,
                "has_price_info": 0,
                "has_policy": 0,
            }
        )
    for d in eliminated:
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SUNDAY_EXAM",
                "category": "ELIMINATION",
                "asr_text": f"员工 {d['name']} 淘汰, 考试分 {d['exam_score']}",
                "trigger_keywords": "淘汰,技能不足,HR",
                "emotion": "DOG",
                "emotion_score": -0.6,
                "has_price_info": 0,
                "has_policy": 0,
            }
        )
    if avg_score > 0:
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SUNDAY_EXAM",
                "category": "EXAM_SUMMARY",
                "asr_text": summary_text,
                "trigger_keywords": "HR,周末考试,员工考试",
                "emotion": "NEUTRAL",
                "emotion_score": 0.2,
                "has_price_info": 0,
                "has_policy": 0,
            }
        )

    print(f"  brain_feed 条目: {len(feed_entries)}")

    if feed_entries:
        cols = ", ".join(feed_entries[0].keys())
        qmarks = ", ".join(["?"] * len(feed_entries[0]))
        sql = f"INSERT INTO mt_fm_brain_feed ({cols}) VALUES ({qmarks})"
        if not DRY_RUN:
            conn.executemany(sql, [tuple(e.values()) for e in feed_entries])
        else:
            for e in feed_entries:
                print(f"  [DRY] brain_feed: {e['stream_name']} | {e['asr_text'][:60]}")

    # 写 knowledge_digest
    digest_summary = summary_text
    _exec(
        conn,
        "INSERT INTO mt_center_knowledge_digest (center_name, digest_type, digest_summary, kp_count) "
        "VALUES (?,?,?,?)",
        ("hr_center", "weekly_hr", digest_summary, len(feed_entries)),
        desc="S4 knowledge_digest weekly_hr",
    )

    # 保存 JSON 报告
    date_str = datetime.now().strftime("%Y%m%d")
    report_path = REPORT_DIR / f"weekly_hr_report_{date_str}.json"
    if not DRY_RUN:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"  HR 报告: {report_path}")


# ══════════════════════════════════════════════════════════════════
# S5. 长假后开市晨会资料生成 (由 holiday_trigger_engine 触发)
# ══════════════════════════════════════════════════════════════════
def s5_holiday_morning_meeting(conn: sqlite3.Connection) -> dict | None:
    """长假最后一天的开市晨会资料生成. 返回处理结果或 None (非长假模式)"""
    if not HOLIDAY_LAST and not HOLIDAY_WEEKEND:
        return None

    print("\n" + "=" * 60)
    print("S5. 长假后开市晨会资料 / 长假周末整合考试")
    print("=" * 60)

    result = {
        'holiday_last': HOLIDAY_LAST,
        'holiday_weekend': HOLIDAY_WEEKEND,
        'actions': [],
    }

    holiday_name = HOLIDAY_LAST or HOLIDAY_WEEKEND or ''

    if HOLIDAY_LAST:
        # ── 长假最后一天 → 生成开市晨会资料 ──
        print(f"  🎯 ROLE_HOLIDAY_LAST_DAY: {holiday_name} 最后一天")
        print(f"  📅 节后第一个交易日: {POST_TRADE_DATE or '(待确认)'}")

        # 1. 晨会简报 (模拟 - 实际可接入财经 API)
        morning_brief = {
            'holiday': holiday_name,
            'pre_market_date': POST_TRADE_DATE or '',
            'generated_at': _now(),
            'outlook': {
                'global_equities': '长假期间外围市场整体平稳, 关注纳斯达克/港股表现',
                'commodities': '国际油价/金价假期波动, 关注能源和黄金板块开盘方向',
                'fx': '人民币汇率中间价, 关注北向资金节后回流力度',
                'crypto': '比特币等加密资产假期走势, 情绪面参考',
            },
            'key_focus': [
                f"{holiday_name}节后首个交易日放量方向",
                '北向资金/融资融券节后流向',
                '长假外围市场映射 (中概股/大宗商品)',
                '长假期间重要政策新闻解读',
            ],
            'risk_flags': [
                '警惕节后高开低走 (假日综合征)',
                '关注节前持仓的利空消息是否落地',
            ],
        }

        print(f"    → 晨会简报要点:")
        for k, v in morning_brief['outlook'].items():
            print(f"      [{k}] {v[:60]}...")

        # 2. 写入 mt_center_knowledge_points (kp_type='morning_meeting')
        _exec(
            conn,
            "INSERT OR IGNORE INTO mt_center_knowledge_points "
            "(center_name, kp_type, knowledge_title, knowledge_body, confidence) "
            "VALUES (?,?,?,?,?)",
            (
                "gobelin_trading",
                "morning_meeting",
                f"{holiday_name}_开市晨会_{POST_TRADE_DATE or _now()[:10]}",
                json.dumps(morning_brief, ensure_ascii=False)[:4000],
                0.9,
            ),
            desc=f"S5 写 knowledge_points morning_meeting",
        )
        result['actions'].append('morning_meeting_brief_generated')

        # 3. 投喂 AI 脑库
        feed_entry = {
            'stream_name': 'HOLIDAY_POST_MARKET_PREP',
            'category': 'MORNING_MEETING',
            'asr_text': (
                f"{holiday_name}节后开市晨会简报 ({POST_TRADE_DATE}). "
                f"外围: {morning_brief['outlook']['global_equities'][:50]}; "
                f"商品: {morning_brief['outlook']['commodities'][:50]}; "
                f"重点关注: {morning_brief['key_focus'][0]}"
            ),
            'trigger_keywords': f'{holiday_name},节后开市,晨会,外围市场',
            'emotion': 'NEUTRAL',
            'emotion_score': 0.1,
            'has_price_info': 1,
            'has_policy': 0,
        }
        if not DRY_RUN:
            cols = ", ".join(feed_entry.keys())
            qmarks = ", ".join(["?"] * len(feed_entry))
            conn.execute(f"INSERT INTO mt_fm_brain_feed ({cols}) VALUES ({qmarks})", tuple(feed_entry.values()))
        result['actions'].append('brain_feed_injected')

        # 4. 触发 direction_pool
        _exec(
            conn,
            "INSERT OR IGNORE INTO mt_center_direction_pool "
            "(center_name, direction_title, seed, status, priority, auto_spawned) "
            "VALUES (?,?,?,?,?,?)",
            (
                "gobelin_trading",
                f"MORNING_MEETING_{holiday_name}_{POST_TRADE_DATE or ''}",
                f"{holiday_name}节后 ({POST_TRADE_DATE}) 开市晨会准备, 外围市场/商品/汇率/北向资金简报",
                "SEED",
                10,
                1,
            ),
            desc=f"S5 direction_pool morning_meeting",
        )
        result['actions'].append('direction_pool_seeded')

    elif HOLIDAY_WEEKEND:
        # ── 长假中间周末 → 合并考试 (在正常 S1-S4 基础上标记) ──
        print(f"  🎯 ROLE_HOLIDAY_WEEKEND: {holiday_name} 中间周末")
        print(f"    → 正常执行考试流程, 但长假期间可能无实际市场操作数据")

        # 额外记录
        _exec(
            conn,
            "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
            (
                "hr_center",
                "HOLIDAY_WEEKEND_EXAM",
                json.dumps({
                    'holiday': holiday_name,
                    'note': '长假中间周末, 合并考试',
                    'generated_at': _now(),
                }, ensure_ascii=False),
            ),
            desc="S5 evolution_log holiday_weekend_exam",
        )
        result['actions'].append('holiday_weekend_exam_marked')

    print(f"  ✓ S5 完成, actions: {result['actions']}")
    return result


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════
def run_weekend_sunday(
    dry_run: bool = False,
    holiday_last: str = None,
    holiday_weekend: str = None,
    post_trade: str = None,
) -> dict:
    """
    周日引擎主入口.

    Args:
        dry_run: 是否干跑
        holiday_last: 长假最后一天模式 (假期名称)
        holiday_weekend: 长假中间周末模式 (假期名称)
        post_trade: 节后第一个交易日日期 (YYYY-MM-DD)
    """
    global DRY_RUN, HOLIDAY_LAST, HOLIDAY_WEEKEND, POST_TRADE_DATE
    DRY_RUN = dry_run
    HOLIDAY_LAST = holiday_last
    HOLIDAY_WEEKEND = holiday_weekend
    POST_TRADE_DATE = post_trade

    holiday_mode_label = ""
    if HOLIDAY_LAST:
        holiday_mode_label = f" [HOLIDAY_LAST: {HOLIDAY_LAST}]"
    elif HOLIDAY_WEEKEND:
        holiday_mode_label = f" [HOLIDAY_WEEKEND: {HOLIDAY_WEEKEND}]"

    print(f"\n{'#'*60}")
    print(f"# Gobelin 周末周日引擎 — {'DRY RUN' if DRY_RUN else 'REAL RUN'}{holiday_mode_label}")
    print(f"# DB: {DB_PATH}")
    print(f"# Ollama: {OLLAMA_URL} model={OLLAMA_MODEL}")
    print(f"# 时间: {_now()}")
    print(f"{'#'*60}\n")

    conn = _connect()
    try:
        # S1 考试
        exam_results = s1_employee_exam(conn)
        # S2 晋升/淘汰
        decisions = s2_promote_eliminate(conn, exam_results)
        # S3 再培训计划
        retrain_stat = s3_retrain_plan(conn, decisions)
        # S4 总结 & 投喂
        s4_summary_and_feed(conn, decisions, retrain_stat)
        # S5 长假后开市晨会资料 (仅长假模式)
        s5 = s5_holiday_morning_meeting(conn)

        if DRY_RUN:
            conn.rollback()
        else:
            conn.commit()

        print(f"\n{'#'*60}")
        print(f"# 周日引擎 {'DRY' if DRY_RUN else 'REAL'} 完成!{holiday_mode_label}")
        print(f"{'#'*60}\n")

        result = {"decisions": decisions, "retrain": retrain_stat}
        if s5:
            result["s5_holiday"] = s5
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Gobelin 周末周日引擎')
    parser.add_argument('mode', nargs='?', default='run',
                        help='run 或 dry')
    parser.add_argument('--holiday-last', default=None,
                        help='长假最后一天模式, 指定假期名称')
    parser.add_argument('--holiday-weekend', default=None,
                        help='长假中间周末模式, 指定假期名称')
    parser.add_argument('--post-trade', default=None,
                        help='节后第一个交易日 (YYYY-MM-DD)')
    args = parser.parse_args()

    run_weekend_sunday(
        dry_run=(args.mode == 'dry'),
        holiday_last=args.holiday_last,
        holiday_weekend=args.holiday_weekend,
        post_trade=args.post_trade,
    )
