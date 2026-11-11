# -*- coding: utf-8 -*-
"""
EDU-2027 P1 — 智能引擎 (AI错因讲解 / 变体题生成 / 难度自动校准)

Step7 AI错因讲解: wrong_book 概念类错题 → qwen2.5 生成个性化讲解 → ai_explanation 列
Step8 变体题生成: 薄弱知识点(mastery<40) 原题 → qwen2.5-coder 变体 → question_bank(source=ai_variant)
Step9 难度校准:   错误率>70% 降档 / <20% 升档 → question_bank.difficulty

daemon: python3 edu_p1_smart_engine.py 常驻, 每 SMART_INTERVAL 秒一轮 (Ollama 限流)
"""
import sqlite3
import json
import time
import signal
import urllib.request
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "database" / "app.db"
SMART_INTERVAL = 900          # 15 分钟一轮 (Ollama 限流)
BATCH = 2                     # 每步每轮最多 2 次 Ollama 调用
OLLAMA = "http://127.0.0.1:11434"
MODEL_CHAT = "qwen2.5:7b"
MODEL_CODE = "qwen2.5-coder:7b"

_running = True


def _stop(sig, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _db(timeout: int = 12):
    conn = sqlite3.connect(str(DB), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=9000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ollama(model: str, prompt: str, num_predict: int = 700) -> str:
    body = {"model": model, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.6, "num_ctx": 4096, "num_predict": num_predict}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=240)
    return json.loads(resp.read()).get("message", {}).get("content", "").strip()


# ────────────── Step7 AI 错因讲解 ──────────────

REASON_HINT = {"concept": "学生是概念性误解(不理解知识点本质)",
               "compute": "学生是计算性失误(思路对但算错)",
               "read": "学生是审题性错误(读题偏差)"}


def step7_ai_explanations(conn) -> int:
    """为无讲解的概念类错题生成 AI 个性化讲解"""
    try:
        conn.execute("ALTER TABLE wrong_book ADD COLUMN ai_explanation TEXT")
        conn.commit()
    except Exception:
        pass
    rows = conn.execute(
        """SELECT w.rowid, w.stem_preview, w.correct_answer, w.user_answer, w.reason_tag,
                  q.knowledge_points, q.explanation
           FROM wrong_book w LEFT JOIN question_bank q ON q.question_id=w.question_id
           WHERE w.reason_tag='concept' AND (w.ai_explanation IS NULL OR w.ai_explanation='')
           LIMIT ?""", (BATCH,)).fetchall()
    n = 0
    for rowid, stem, ans, user_ans, reason, kps, base_exp in rows:
        try:
            kp = ", ".join(json.loads(kps)[:3]) if kps else "未标注"
        except Exception:
            kp = "未标注"
        prompt = f"""你是一线教师。学生做错了这道题, {REASON_HINT.get(reason, '出错了')}。
题目: {stem[:200]}
学生答案: {user_ans} | 正确答案: {ans}
涉及知识点: {kp}
参考解析: {(base_exp or '')[:150]}

请写一段 120 字以内的针对性讲解, 结构: [错在哪] 一句话点破误区 → [怎么想] 正确思路 → [记住] 一句口诀。直接输出, 不要客套。"""
        try:
            exp = _ollama(MODEL_CHAT, prompt, num_predict=400)
            if exp:
                conn.execute("UPDATE wrong_book SET ai_explanation=? WHERE rowid=?", (exp[:800], rowid))
                n += 1
        except Exception:
            continue
    conn.commit()
    return n


# ────────────── Step8 变体题生成 ──────────────

def step8_variants(conn) -> int:
    """为最薄弱知识点 (mastery<40) 从题库找原型 → 生成变体题入库"""
    weak = conn.execute(
        """SELECT knowledge_point, MIN(mastery_level) FROM user_knowledge_mastery
           WHERE mastery_level < 40 GROUP BY knowledge_point LIMIT ?""", (BATCH,)).fetchall()
    n = 0
    for kp, lvl in weak:
        seed = conn.execute(
            """SELECT id, subject, grade, question_type, difficulty, content, options, answer, explanation
               FROM question_bank WHERE knowledge_points LIKE ? AND source != 'ai_variant'
               ORDER BY RANDOM() LIMIT 1""", (f"%{kp}%",)).fetchone()
        if not seed:
            continue
        qid, subject, grade, qtype, diff, content, options, answer, explanation = seed
        prompt = f"""你是命题专家。基于下面这道"{kp}"的原题, 出一道同考点变体题: 换数字/换情境, 考查同一个知识点, 难度相近。

原题({qtype}, 答案={answer}): {content[:250]}
选项: {str(options)[:200] if options else '(无选项)'}

严格按 JSON 输出, 不要其他文字:
{{"content": "变体题干", "options": ["A...", "B...", "C...", "D..."], "answer": "X", "explanation": "简短解析"}}"""
        try:
            raw = _ollama(MODEL_CODE, prompt, num_predict=500)
            s, e = raw.find("{"), raw.rfind("}")
            if s < 0 or e <= s:
                continue
            v = json.loads(raw[s:e + 1])
            if not v.get("content") or not v.get("answer"):
                continue
            new_qid = f"ai_var_{kp[:8]}_{int(time.time())}"
            conn.execute("""INSERT INTO question_bank(question_id,subject,grade,question_type,difficulty,
                            content,options,answer,explanation,knowledge_points,source,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                         (new_qid, subject, grade, qtype, diff,
                          str(v["content"])[:500],
                          json.dumps(v.get("options", []), ensure_ascii=False)[:500],
                          str(v.get("answer", ""))[:10],
                          str(v.get("explanation", ""))[:400],
                          json.dumps([kp], ensure_ascii=False), "ai_variant"))
            n += 1
        except Exception:
            continue
    conn.commit()
    return n


# ────────────── Step9 难度自动校准 ──────────────

DIFF_ORDER = ["easy", "medium", "hard"]
DIFF_UP = {"easy": "medium", "medium": "hard"}
DIFF_DOWN = {"hard": "medium", "medium": "easy"}


def step9_calibrate(conn) -> int:
    """全库统计每题真实错误率: >70% 降档(太难) / <20% 升档(太易)"""
    # 用飞轮产生的作答数据 (exam_sessions.answers_json)
    rows = conn.execute(
        "SELECT answers_json FROM exam_sessions WHERE status='completed' AND answers_json IS NOT NULL "
        "ORDER BY rowid DESC LIMIT 60").fetchall()
    stats = {}
    for (aj,) in rows:
        try:
            for a in json.loads(aj):
                qid = a.get("qid")
                if qid:
                    s = stats.setdefault(qid, [0, 0])
                    s[0] += 1
                    if not a.get("right"):
                        s[1] += 1
        except Exception:
            continue
    n = 0
    for qid, (total, wrong) in stats.items():
        if total < 3:
            continue
        rate = wrong / total
        row = conn.execute("SELECT difficulty FROM question_bank WHERE question_id=?", (qid,)).fetchone()
        if not row:
            continue
        diff = (row[0] or "medium").lower()
        new_diff = None
        if rate > 0.7 and diff in DIFF_DOWN:
            new_diff = DIFF_DOWN[diff]      # 太难 → 降档
        elif rate < 0.2 and diff in DIFF_UP:
            new_diff = DIFF_UP[diff]        # 太易 → 升档
        if new_diff and new_diff != diff:
            conn.execute("UPDATE question_bank SET difficulty=? WHERE question_id=?", (new_diff, qid))
            conn.execute("""INSERT INTO question_difficulty_calibration(question_id, old_difficulty,
                            new_difficulty, error_rate, sample_size, calibrated_at, calibrated_by)
                            VALUES(?,?,?,?,?,datetime('now','localtime'),'edu_p1')""",
                         (qid, diff, new_diff, round(rate, 2), total))
            n += 1
    conn.commit()
    return n


# ────────────── 主循环 ──────────────

def smart_once() -> dict:
    conn = _db()
    out = {}
    try:
        out["explanations"] = step7_ai_explanations(conn)
        out["variants"] = step8_variants(conn)
        out["calibrated"] = step9_calibrate(conn)
    finally:
        conn.close()
    return out


def main():
    print(f"[EDU-P1] 智能引擎启动 · 每 {SMART_INTERVAL}s 一轮 · Ollama={OLLAMA}", flush=True)
    while _running:
        try:
            r = smart_once()
            if any(r.values()):
                print(f"[EDU-P1] {datetime.now().strftime('%H:%M:%S')} {r}", flush=True)
        except Exception as ex:
            print(f"[EDU-P1] ⚠️ {str(ex)[:200]}", flush=True)
            time.sleep(30)
        for _ in range(SMART_INTERVAL):
            if not _running:
                break
            time.sleep(1)
    print("[EDU-P1] 退出", flush=True)


if __name__ == "__main__":
    main()
