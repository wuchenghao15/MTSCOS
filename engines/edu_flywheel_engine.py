# -*- coding: utf-8 -*-
"""
EDU-2027 P0 — 教育飞轮引擎 (诊断→处方→练习→复测 自驱闭环)

点火空转的学习闭环表:
  wrong_book / exam_sessions / exam_results / user_knowledge_mastery /
  learning_paths / daily_practice

6 步飞轮 (每轮限流, 幂等, WAL 小事务):
  Step1 自动组卷: question_bank 按学科抽题 → paper_instances → exam_sessions
  Step2 智能作答: 按 k12_students.tier 概率作答 → exam_results → 错题入 wrong_book
  Step3 掌握度:   错题知识点 → user_knowledge_mastery (错- 对+)
  Step4 处方:     mastery<60% 知识点 → learning_paths 自动生成
  Step5 每日练习: wrong_book 未掌握题 + 薄弱点新题 → daily_practice
  Step6 复测:     练习结果 → mastery 回升 → is_mastered → 路径 progress 推进

daemon 模式: python3 edu_flywheel_engine.py 常驻, 每 FLYWHEEL_INTERVAL 秒一轮
"""
import sqlite3
import json
import time
import hashlib
import random
import signal
import sys
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "database" / "app.db"
FLYWHEEL_INTERVAL = 600          # 10 分钟一轮
BATCH = 3                        # 每轮每步最多处理数 (限流保 WAL)
TIER_ACC = {"A": 0.85, "B": 0.65, "C": 0.45}   # tier→正确率

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


def _det_rand(*seeds) -> float:
    """确定性伪随机 [0,1) — 同种子同结果, 保证幂等复现"""
    h = hashlib.md5("|".join(str(s) for s in seeds).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


# ────────────── Step1 自动组卷 ──────────────

def step1_build_papers(conn) -> int:
    """从 question_bank 按学科抽 5 题组卷 → 为未参考学生建 exam_sessions"""
    students = conn.execute(
        "SELECT user_id, grade, tier FROM k12_students ORDER BY id LIMIT 200").fetchall()
    if not students:
        return 0
    n = 0
    for uid, grade, tier in students:
        uid = str(uid)
        if n >= BATCH:
            break
        existing = conn.execute(
            "SELECT COUNT(*) FROM exam_sessions WHERE user_id=? AND status IN ('in_progress','completed')",
            (uid,)).fetchone()[0]
        if existing >= 2:      # 每学生最多 2 个未复测 session
            continue
        qs = conn.execute(
            """SELECT id, question_id, subject, question_type, difficulty, content, options,
                      answer, explanation, knowledge_points
               FROM question_bank WHERE grade=? ORDER BY RANDOM() LIMIT 5""", (grade,)).fetchall()
        if len(qs) < 3:
            qs = conn.execute(
                """SELECT id, question_id, subject, question_type, difficulty, content, options,
                          answer, explanation, knowledge_points
                   FROM question_bank ORDER BY RANDOM() LIMIT 5""").fetchall()
        if not qs:
            continue
        pid = f"FP_{uid[:12]}_{datetime.now().strftime('%y%m%d%H%M%S')}_{random.randint(100,999)}"
        qids = [q[1] for q in qs]
        conn.execute("""INSERT INTO paper_instances(paper_id,paper_name,subject,total_score,
                        duration_min,question_count,question_ids_json,paper_json,created_by,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                     (pid, f"飞轮诊断卷·{grade}", qs[0][2] if qs else "综合",
                      len(qs) * 20, 30, len(qs), json.dumps(qids),
                      json.dumps([{"id": q[1], "type": q[3], "difficulty": q[4],
                                   "content": q[5][:120], "kp": q[9]} for q in qs], ensure_ascii=False),
                      "edu_flywheel"))
        sid = f"ES_{uid[:12]}_{datetime.now().strftime('%y%m%d%H%M%S')}_{random.randint(100,999)}"
        conn.execute("""INSERT INTO exam_sessions(session_id,user_id,exam_id,start_time,status)
                        VALUES(?,?,?,datetime('now','localtime'),?)""",
                     (sid, uid, pid, "in_progress"))
        n += 1
    conn.commit()
    return n


# ────────────── Step2 智能作答 → 成绩 + 错题本 ──────────────

def step2_sit_exams(conn) -> int:
    """in_progress session 自动作答 (tier 概率) → exam_results → 错题入 wrong_book"""
    sessions = conn.execute(
        "SELECT session_id, user_id, exam_id FROM exam_sessions WHERE status='in_progress' LIMIT ?",
        (BATCH,)).fetchall()
    n = 0
    for sid, uid, pid in sessions:
        uid = str(uid)
        tier_row = conn.execute("SELECT tier FROM k12_students WHERE user_id=?", (uid,)).fetchone()
        tier = (tier_row[0] if tier_row else "B").strip().upper()[:1]
        acc = TIER_ACC.get(tier, 0.6)
        qs = conn.execute(
            """SELECT question_id, subject, question_type, content, answer, knowledge_points
               FROM question_bank WHERE question_id IN
               (SELECT value FROM json_each(?))""",
            (conn.execute("SELECT question_ids_json FROM paper_instances WHERE paper_id=?",
                          (pid,)).fetchone()[0],)).fetchall()
        if not qs:
            conn.execute("UPDATE exam_sessions SET status='void' WHERE session_id=?", (sid,))
            conn.commit()
            continue
        correct, wrong, answers = 0, 0, []
        for qid, subject, qtype, content, ans, kps in qs:
            is_right = _det_rand(uid, qid) < acc
            # 模拟用户答案
            if is_right or not ans:
                user_ans = ans
            else:
                user_ans = "X"          # 错答占位 (真实场景来自前端)
            answers.append({"qid": qid, "user": user_ans, "right": is_right,
                            "kp": kps, "subject": subject})
            if is_right:
                correct += 1
            else:
                wrong += 1
                # 错题入本 (幂等: 同人同题不重复)
                dup = conn.execute("SELECT 1 FROM wrong_book WHERE user_id=? AND question_id=? AND is_mastered=0",
                                   (uid, qid)).fetchone()
                if not dup:
                    conn.execute("""INSERT INTO wrong_book(user_id,question_id,subject,question_type,
                                    stem_preview,user_answer,correct_answer,reason_tag,is_mastered,
                                    review_count,created_at)
                                    VALUES(?,?,?,?,?,?,?,?,'0',0,datetime('now','localtime'))""",
                                 (uid, qid, subject, qtype, (content or "")[:100],
                                  user_ans, ans, _det_reason(uid, qid)))
        score = correct * 20
        conn.execute("""UPDATE exam_sessions SET status='completed', end_time=datetime('now','localtime'),
                        answers_json=?, score=?, correct_count=?, wrong_count=?, skip_count=0
                        WHERE session_id=?""",
                     (json.dumps(answers, ensure_ascii=False), score, correct, wrong, sid))
        conn.execute("""INSERT INTO exam_results(result_id,user_id,exam_id,exam_name,exam_type,subject,
                        total_score,score,pass_score,is_pass,grade,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                     (f"R_{sid}", uid, pid, "飞轮诊断卷", "diagnostic",
                      qs[0][1] if qs else "综合", len(qs) * 20, score, 60,
                      1 if score >= 60 else 0, tier))
        n += 1
    conn.commit()
    return n


def _det_reason(uid, qid) -> str:
    """错因三分类 (确定性): concept/compute/read"""
    r = _det_rand("reason", uid, qid)
    return ("concept" if r < 0.45 else "compute" if r < 0.75 else "read")


# ────────────── Step3 掌握度更新 ──────────────

def _ensure_apply_col(conn):
    """wrong_book.mastery_applied 幂等标记 (best-effort)"""
    try:
        conn.execute("ALTER TABLE wrong_book ADD COLUMN mastery_applied INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # 列已存在


def step3_update_mastery(conn) -> int:
    """错题 → mastery -12 (仅首次, mastery_applied 幂等); 复测对题 → +15 (范围 0-100)"""
    _ensure_apply_col(conn)
    wrongs = conn.execute(
        """SELECT w.rowid, w.user_id, w.question_id, q.knowledge_points
           FROM wrong_book w LEFT JOIN question_bank q ON q.question_id=w.question_id
           WHERE w.is_mastered='0' AND COALESCE(w.mastery_applied,0)=0 LIMIT ?""",
        (BATCH * 3,)).fetchall()
    n = 0
    for rowid, uid, qid, kps in wrongs:
        uid = str(uid)
        try:
            points = json.loads(kps) if kps else []
        except Exception:
            points = []
        for kp in points[:2]:
            if not kp:
                continue
            row = conn.execute("SELECT mastery_level FROM user_knowledge_mastery "
                               "WHERE user_id=? AND knowledge_point=?", (uid, kp)).fetchone()
            if row:
                new_level = max(5, row[0] - 12)   # 保底 5, 留复测回升空间
                conn.execute("""UPDATE user_knowledge_mastery SET mastery_level=?, updated_at=datetime('now','localtime')
                                WHERE user_id=? AND knowledge_point=?""", (new_level, uid, kp))
            else:
                conn.execute("""INSERT INTO user_knowledge_mastery(user_id,knowledge_point,mastery_level,
                                practice_count,correct_count,last_practiced,updated_at)
                                VALUES(?,?,48,0,0,datetime('now','localtime'),datetime('now','localtime'))""",
                             (uid, kp))
            n += 1
        conn.execute("UPDATE wrong_book SET mastery_applied=1 WHERE rowid=?", (rowid,))
    conn.commit()
    return n


def _col_exists(conn, table, col) -> bool:
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return col in cols


# ────────────── Step4 学习路径处方 ──────────────

def step4_prescribe_paths(conn) -> int:
    """mastery<60 且无路径的知识点 → learning_paths 生成"""
    weak = conn.execute(
        """SELECT user_id, knowledge_point, mastery_level FROM user_knowledge_mastery
           WHERE mastery_level < 60 LIMIT ?""", (BATCH * 2,)).fetchall()
    n = 0
    for uid, kp, lvl in weak:
        uid = str(uid)
        dup = conn.execute("SELECT 1 FROM learning_paths WHERE user_id=? AND path_id=?",
                           (uid, f"LP_{hashlib.md5((uid+kp).encode()).hexdigest()[:16]}")).fetchone()
        if dup:
            continue
        # 从题库找该知识点的练习题
        drills = conn.execute(
            "SELECT question_id FROM question_bank WHERE knowledge_points LIKE ? LIMIT 6",
            (f"%{kp}%",)).fetchall()
        path_id = f"LP_{hashlib.md5((uid+kp).encode()).hexdigest()[:16]}"
        path_data = {
            "knowledge_point": kp,
            "current_mastery": lvl,
            "stages": [
                {"stage": 1, "action": "重练错题", "done": False},
                {"stage": 2, "action": "变体题训练", "drills": [d[0] for d in drills[:4]], "done": False},
                {"stage": 3, "action": "复测达标(≥75)", "done": False},
            ],
        }
        conn.execute("""INSERT INTO learning_paths(user_id,path_id,subject,current_level,target_level,
                        path_data,progress,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,0,datetime('now','localtime'),datetime('now','localtime'))""",
                     (uid, path_id, "综合", lvl, 75, json.dumps(path_data, ensure_ascii=False)))
        n += 1
    conn.commit()
    return n


# ────────────── Step5 每日练习 ──────────────

def step5_daily_practice(conn) -> int:
    """为有错题/薄弱点的学生生成今日练习记录 (幂等: 每人每日一条)"""
    today = datetime.now().strftime("%Y-%m-%d")
    students = conn.execute(
        """SELECT DISTINCT user_id FROM wrong_book WHERE is_mastered='0'
           UNION SELECT DISTINCT user_id FROM user_knowledge_mastery WHERE mastery_level<60
           LIMIT ?""", (BATCH,)).fetchall()
    n = 0
    for (uid,) in students:
        uid = str(uid)
        dup = conn.execute("SELECT 1 FROM daily_practice WHERE user_id=? AND practice_date=?",
                           (uid, today)).fetchone()
        if dup:
            continue
        review_n = conn.execute("SELECT COUNT(*) FROM wrong_book WHERE user_id=? AND is_mastered='0'",
                                (uid,)).fetchone()[0]
        new_n = conn.execute("""SELECT COUNT(*) FROM user_knowledge_mastery
                                WHERE user_id=? AND mastery_level<60""", (uid,)).fetchone()[0]
        total = min(10, review_n + new_n) or 5
        conn.execute("""INSERT INTO daily_practice(daily_id,user_id,practice_date,subject,
                        total_questions,correct_count,accuracy,duration_min,is_completed,streak_days,created_at)
                        VALUES(?,?,?,?,?,0,NULL,NULL,0,0,datetime('now','localtime'))""",
                     (f"DP_{uid[:10]}_{today.replace('-', '')}", uid, today, "综合", total))
        n += 1
    conn.commit()
    return n


# ────────────── Step6 复测回升 + 路径推进 ──────────────

def step6_retest(conn) -> int:
    """练习完成 → 薄弱点按 tier 概率回升 → mastery≥75 则错题标记 mastered + 路径推进"""
    plans = conn.execute(
        "SELECT daily_id, user_id, total_questions FROM daily_practice WHERE is_completed=0 LIMIT ?",
        (BATCH,)).fetchall()
    n = 0
    for did, uid, total in plans:
        uid = str(uid)
        tier_row = conn.execute("SELECT tier FROM k12_students WHERE user_id=?", (uid,)).fetchone()
        acc = TIER_ACC.get((tier_row[0] if tier_row else "B").strip().upper()[:1], 0.6)
        correct = sum(1 for i in range(total) if _det_rand("retest", uid, did, i) < acc)
        accuracy = round(correct / max(total, 1), 2)
        # 薄弱点回升
        weak = conn.execute("""SELECT knowledge_point, mastery_level FROM user_knowledge_mastery
                               WHERE user_id=? AND mastery_level<60 LIMIT 3""", (uid,)).fetchall()
        for kp, lvl in weak:
            if _det_rand("lift", uid, kp, did) < acc:
                new_lvl = min(100, lvl + 18)
                conn.execute("""UPDATE user_knowledge_mastery SET mastery_level=?, practice_count=practice_count+1,
                                correct_count=correct_count+1, last_practiced=datetime('now','localtime'),
                                updated_at=datetime('now','localtime') WHERE user_id=? AND knowledge_point=?""",
                             (new_lvl, uid, kp))
                # 每次成功复测路径推进 +12; 达标(≥75)额外错题标掌握
                conn.execute("""UPDATE learning_paths SET progress=MIN(100, progress+12),
                                updated_at=datetime('now','localtime') WHERE user_id=? AND path_id=?""",
                             (uid, f"LP_{hashlib.md5((uid+kp).encode()).hexdigest()[:16]}"))
                if new_lvl >= 75:
                    conn.execute("""UPDATE wrong_book SET is_mastered='1', last_review_at=datetime('now','localtime')
                                    WHERE user_id=? AND is_mastered='0' AND question_id IN
                                    (SELECT question_id FROM question_bank WHERE knowledge_points LIKE ?)""",
                                 (uid, f"%{kp}%"))
        conn.execute("""UPDATE daily_practice SET correct_count=?, accuracy=?, duration_min=?,
                        is_completed=1, streak_days=
                        COALESCE((SELECT streak_days FROM daily_practice WHERE user_id=? AND is_completed=1
                                  AND practice_date < ? ORDER BY practice_date DESC LIMIT 1),0)+1
                        WHERE daily_id=?""",
                     (correct, accuracy, random.randint(8, 25), uid, did.split("_")[-1][:4] and datetime.now().strftime("%Y-%m-%d"), did))
        n += 1
    conn.commit()
    return n


# ────────────── 主循环 ──────────────

def flywheel_once() -> dict:
    conn = _db()
    out = {}
    try:
        out["papers"] = step1_build_papers(conn)
        out["exams"] = step2_sit_exams(conn)
        out["mastery"] = step3_update_mastery(conn)
        out["paths"] = step4_prescribe_paths(conn)
        out["daily"] = step5_daily_practice(conn)
        out["retest"] = step6_retest(conn)
    finally:
        conn.close()
    return out


def main():
    print(f"[EDU-FLYWHEEL] 启动 · 每 {FLYWHEEL_INTERVAL}s 一轮 · DB={DB}", flush=True)
    while _running:
        try:
            r = flywheel_once()
            if any(r.values()):
                print(f"[EDU-FLYWHEEL] {datetime.now().strftime('%H:%M:%S')} {r}", flush=True)
        except Exception as ex:
            print(f"[EDU-FLYWHEEL] ⚠️ {str(ex)[:200]}", flush=True)
            time.sleep(30)
        for _ in range(FLYWHEEL_INTERVAL):
            if not _running:
                break
            time.sleep(1)
    print("[EDU-FLYWHEEL] 退出", flush=True)


if __name__ == "__main__":
    main()
