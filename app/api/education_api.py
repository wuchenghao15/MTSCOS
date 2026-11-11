#!/usr/bin/env python3
"""
§二 教育全链条 + §三 个性化 + §四.5 模型升级 — Flask API 三合一
合并为一个文件减少路由注册开销
"""
import sqlite3, os, json, time, re, urllib.request, urllib.error
from datetime import datetime
from flask import Blueprint, jsonify, request

education_api = Blueprint('education_api', __name__)

def _db():
    for p in [
        # server_real_db.APP_DB 真实路径
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '_runtime', 'databases', 'Database', 'app.db')),
        os.path.expanduser('~/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/_runtime/databases/Database/app.db'),
        os.path.expanduser('~/mtscos/_runtime/databases/Database/app.db'),
    ]:
        if os.path.exists(p):
            conn = sqlite3.connect(p); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL")
            return conn

# ===== Ollama 推理（§二 错题思维链核心）=====
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("EDU_OLLAMA_MODEL", "qwen2.5:7b")

def _ollama_generate(prompt: str, model: str = None, timeout: int = 60) -> str:
    """调用 Ollama /api/generate，带超时和重试"""
    tag = model or _OLLAMA_MODEL
    last_err = None
    for attempt in range(2):  # 最多 2 次
        try:
            req = urllib.request.Request(
                f"{_OLLAMA_HOST}/api/generate",
                data=json.dumps({
                    "model": tag,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3}  # 低温度 = 更确定的 JSON 输出
                }).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
                return data.get("response", "")
        except Exception as e:
            last_err = str(e)
            time.sleep(1)
    raise RuntimeError(f"Ollama generate 失败 (model={tag}): {last_err}")

def _extract_json(text: str) -> dict:
    """从 AI 输出中健壮地提取 JSON（处理可能的 Markdown 代码块包裹）"""
    # 先尝试直接 json.loads
    try:
        return json.loads(text)
    except: pass
    # 去掉 ```json ... ``` 包裹
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    # 找第一个 { 到最后一个 } 之间
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try: return json.loads(text[start:end+1])
        except: pass
    return None

# ============ §二.1 错题思维链 ============

@education_api.route('/api/edu/error_chain', methods=['GET'])
def list_error_chains():
    user = request.args.get('user_id', 'wuchenghao15')
    subj = request.args.get('subject')
    conn = _db()
    sql = "SELECT * FROM mt_error_thinking_chain WHERE user_id=?"
    args = [user]
    if subj: sql += " AND subject=?"; args.append(subj)
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return jsonify({"success": True, "data": [dict(r) for r in rows], "total": len(rows)})

@education_api.route('/api/edu/error_chain/analyze', methods=['POST'])
def analyze_error_chain():
    """
    §二.1 核心：接收错题 → Ollama 推理用户思维链 → 落库
    POST JSON: {
        "user_id": "wuchenghao15",
        "subject": "数学",
        "grade_level": "高等",
        "question_text": "求∫x*e^x dx",
        "user_answer": "e^x",
        "correct_answer": "(x-1)*e^x + C",
        "hint": "",           // 可选：额外提示
        "model": ""           // 可选：指定 Ollama 模型
    }
    """
    body = request.get_json(force=True) or {}
    required = ['question_text', 'user_answer', 'correct_answer']
    for f in required:
        if not body.get(f):
            return jsonify({"success": False, "error": f"缺少必要字段: {f}"}), 400
    
    question   = body['question_text'].strip()
    user_ans   = body['user_answer'].strip()
    correct    = body['correct_answer'].strip()
    subject    = body.get('subject', '未分类')
    grade      = body.get('grade_level', 'auto')
    user_id    = body.get('user_id', 'wuchenghao15')
    hint       = body.get('hint', '')
    model      = body.get('model') or _OLLAMA_MODEL
    
    # ===== 专业 Prompt Engineering =====
    prompt = f"""你是一位资深教育诊断 AI。下面是一道错题，请你精准分析学生的思维过程，找出错因，并给出具体修复建议。

【题目】
{question}

【学生答案】
{user_ans}

【正确答案】
{correct}

【学科】{subject}  【学段】{grade}
{"【额外提示】" + hint if hint else ""}

请严格输出以下 JSON 格式（不要加任何多余文字或 Markdown）：
{{
  "error_type": "概念误解|计算错误|逻辑跳步|粗心大意|知识断层|公式误用|步骤遗漏",
  "thinking_chain": [
    "1. 学生第一步...",
    "2. 学生第二步...",
    "3. 关键错误发生在哪一步...",
    "4. 缺失/错误的思维环节是..."
  ],
  "missing_concepts": ["缺失的知识点1", "缺失的知识点2"],
  "confidence": 0.0-1.0,
  "suggested_fix": "具体可操作的修复建议（练习量/复习方向/思维训练方法）",
  "next_step_question": "针对该错因设计的下一道训练题"
}}"""
    
    # ===== 调 Ollama =====
    t0 = time.time()
    try:
        raw = _ollama_generate(prompt, model=model, timeout=90)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 503
    latency_ms = (time.time() - t0) * 1000
    
    # ===== 解析 JSON =====
    parsed = _extract_json(raw)
    if not parsed:
        # JSON 解析失败，把原始输出也带上让前端知道
        parsed = {
            "error_type": "未分类",
            "thinking_chain": ["AI 输出非结构化，需要人工复核"],
            "suggested_fix": "请检查 AI 原始输出",
            "raw_ai_output": raw[:1000],
            "confidence": 0.0,
        }
    
    # ===== 落库 =====
    thinking_chain = json.dumps(parsed.get('thinking_chain', []), ensure_ascii=False)
    error_type     = parsed.get('error_type', '未分类')
    suggested_fix  = parsed.get('suggested_fix', '')
    missing        = json.dumps(parsed.get('missing_concepts', []), ensure_ascii=False)
    
    conn = _db()
    cur = conn.execute("""INSERT INTO mt_error_thinking_chain
        (user_id, subject, grade_level, question_text, user_answer, correct_answer,
         error_type, thinking_chain, suggested_fix, ai_model)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (user_id, subject, grade, question, user_ans, correct,
         error_type, thinking_chain, suggested_fix, model))
    chain_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "chain_id": chain_id,
        "ai_model": model,
        "latency_ms": round(latency_ms),
        "analysis": {
            "error_type": error_type,
            "thinking_chain": json.loads(thinking_chain),
            "missing_concepts": json.loads(missing),
            "confidence": parsed.get('confidence', 0.5),
            "suggested_fix": suggested_fix,
            "next_step_question": parsed.get('next_step_question', ''),
        }
    })

@education_api.route('/api/edu/error_chain/<int:chain_id>', methods=['GET'])
def get_error_chain(chain_id):
    conn = _db()
    row = conn.execute("SELECT * FROM mt_error_thinking_chain WHERE chain_id=?", (chain_id,)).fetchone()
    if not row: conn.close(); return jsonify({"success": False, "error": "不存在"}), 404
    d = dict(row)
    d['thinking_chain'] = json.loads(d.get('thinking_chain') or '[]')
    conn.close()
    return jsonify({"success": True, "data": d})

# ============ §二.3 学习路径 ============

@education_api.route('/api/edu/learning_path', methods=['GET'])
def list_learning_paths():
    user = request.args.get('user_id', 'wuchenghao15')
    conn = _db()
    rows = conn.execute("SELECT * FROM mt_learning_path WHERE user_id=? ORDER BY updated_at DESC", (user,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['gaps'] = json.loads(d.get('gaps') or '[]')
        d['recommended_resources'] = json.loads(d.get('recommended_resources') or '[]')
        result.append(d)
    return jsonify({"success": True, "data": result})

# ============ §二.3 AI 导师 ============

@education_api.route('/api/edu/tutor/sessions', methods=['GET'])
def tutor_sessions():
    user = request.args.get('user_id', 'wuchenghao15')
    conn = _db()
    rows = conn.execute("SELECT * FROM mt_ai_tutor_session WHERE user_id=? AND status='active' ORDER BY last_active DESC", (user,)).fetchall()
    conn.close()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})

@education_api.route('/api/edu/tutor/types', methods=['GET'])
def tutor_types():
    """7 类 AI 导师类型（战略 §二.3）"""
    types = [
        {"code": "general",  "name": "AI全科学习导师", "desc": "全学科学习引导/错题分析/思维链诊断", "matrix": "matrix_edu"},
        {"code": "psych",    "name": "AI心理导师",     "desc": "情绪识别/动机建模/微量数据推演",   "matrix": "matrix_psych"},
        {"code": "research", "name": "AI科研导师",     "desc": "论文全链路/课题生成/前沿推演",     "matrix": "matrix_research"},
        {"code": "career",   "name": "AI职业导师",     "desc": "赛道分析/职业匹配/转型规划",       "matrix": "matrix_career"},
        {"code": "code",     "name": "AI代码导师",     "desc": "代码review/Bug分析/架构建议",      "matrix": "matrix_code"},
        {"code": "edu_sys",  "name": "AI系统导师",     "desc": "系统运维/AI员工/架构演进",         "matrix": "matrix_ops"},
        {"code": "security", "name": "AI安全导师",     "desc": "安全审计/密码学/权限合规",         "matrix": "matrix_security"},
    ]
    return jsonify({"success": True, "data": types, "total": len(types)})

# ============ §三 前端个性化 ============

@education_api.route('/api/profile/cognitive', methods=['GET'])
def cognitive_profile():
    user = request.args.get('user_id', 'wuchenghao15')
    conn = _db()
    row = conn.execute("SELECT * FROM mt_user_cognitive_profile WHERE user_id=?", (user,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": True, "data": None, "message": "该用户暂无画像，AI 会根据行为数据自动生成"})
    d = dict(row)
    d['focus_subjects'] = json.loads(d.get('focus_subjects') or '[]')
    d['weak_subjects'] = json.loads(d.get('weak_subjects') or '[]')
    return jsonify({"success": True, "data": d})

@education_api.route('/api/profile/recommendations', methods=['GET'])
def recommendations():
    user = request.args.get('user_id', 'wuchenghao15')
    conn = _db()
    rows = conn.execute("SELECT * FROM mt_personalized_recommendation WHERE user_id=? AND dismissed=0 ORDER BY created_at DESC LIMIT 10", (user,)).fetchall()
    conn.close()
    return jsonify({"success": True, "data": [dict(r) for r in rows]})

@education_api.route('/api/profile/stats', methods=['GET'])
def profile_stats():
    conn = _db()
    profiles = conn.execute("SELECT COUNT(*) FROM mt_user_cognitive_profile").fetchone()[0]
    chains = conn.execute("SELECT COUNT(*) FROM mt_error_thinking_chain").fetchone()[0]
    paths = conn.execute("SELECT COUNT(*) FROM mt_learning_path").fetchone()[0]
    tutors = conn.execute("SELECT COUNT(*) FROM mt_ai_tutor_session").fetchone()[0]
    recs = conn.execute("SELECT COUNT(*) FROM mt_personalized_recommendation").fetchone()[0]
    conn.close()
    return jsonify({
        "success": True,
        "profiles": profiles,
        "error_chains": chains,
        "learning_paths": paths,
        "tutor_sessions": tutors,
        "recommendations": recs,
    })

# ============ §四.5 大模型升级 API ============

@education_api.route('/api/model/status', methods=['GET'])
def model_status():
    from ai_engines.model_upgrade_engine import model_upgrade_engine as eng
    return jsonify({"success": True, "data": eng.get_status()})

@education_api.route('/api/model/sync', methods=['POST'])
def model_sync():
    from ai_engines.model_upgrade_engine import model_upgrade_engine as eng
    return jsonify({"success": True, "data": eng.sync_ollama()})

@education_api.route('/api/model/<tag>/eval', methods=['POST'])
def model_eval(tag):
    from ai_engines.model_upgrade_engine import model_upgrade_engine as eng
    rounds = int(request.args.get('rounds', 2))
    return jsonify({"success": True, "data": eng.eval_model(tag, rounds)})

@education_api.route('/api/model/<tag>/activate', methods=['POST'])
def model_activate(tag):
    from ai_engines.model_upgrade_engine import model_upgrade_engine as eng
    return jsonify({"success": True, "data": eng.activate(tag)})

@education_api.route('/api/model/<tag>/rollback', methods=['POST'])
def model_rollback(tag):
    from ai_engines.model_upgrade_engine import model_upgrade_engine as eng
    return jsonify({"success": True, "data": eng.rollback(tag)})

# ============ §二 批量错题分析 ============
import threading as _threading

_batch_store = {}   # batch_id -> {status, progress, results, error}
_batch_lock = _threading.Lock()

def _run_single_edu_analyze(q: dict, model: str) -> dict:
    """内部函数：分析一道题，返回与 analyze_error_chain 相同结构"""
    prompt = f"""你是一位资深教育诊断 AI。分析这道错题。输出严格 JSON。
题目: {q.get('question_text','')}
学生答案: {q.get('user_answer','')}
正确答案: {q.get('correct_answer','')}
学科: {q.get('subject','未分类')}  学段: {q.get('grade_level','auto')}
输出 JSON:
{{"error_type":"...","thinking_chain":["...","..."],"missing_concepts":["..."],"confidence":0.0-1.0,"suggested_fix":"...","next_step_question":"..."}}"""
    t0 = time.time()
    raw = _ollama_generate(prompt, model=model, timeout=90)
    latency = round((time.time() - t0) * 1000)
    parsed = _extract_json(raw) or {"error_type":"未分类","thinking_chain":[],"confidence":0.0,"suggested_fix":"AI输出非结构化"}
    parsed["ai_latency_ms"] = latency
    parsed["ai_model"] = model
    parsed["question"] = q
    return parsed

@education_api.route('/api/edu/error_chain/batch_analyze', methods=['POST'])
def batch_analyze():
    """
    批量错题分析（后台异步，threading）
    POST: {"questions": [{question_text,user_answer,correct_answer,subject?,grade_level?}, ...], "model": ""}
    返回: {"batch_id": "...", "total": N, "message": "已开始分析，进度查询 /api/edu/error_chain/batch/<batch_id>"}
    """
    body = request.get_json(force=True) or {}
    questions = body.get('questions', [])
    model = body.get('model') or _OLLAMA_MODEL
    user_id = body.get('user_id', 'wuchenghao15')
    
    if not questions:
        return jsonify({"success": False, "error": "questions 数组不能为空"}), 400
    
    batch_id = f"batch_{int(time.time()*1000) % 100000000}"
    total = len(questions)
    
    # 初始化状态
    with _batch_lock:
        _batch_store[batch_id] = {
            "batch_id": batch_id, "user_id": user_id,
            "model": model, "total": total, "done": 0,
            "status": "running", "results": [], "errors": [],
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
        }
    
    def _worker():
        with _batch_lock:
            state = _batch_store[batch_id]
        for i, q in enumerate(questions):
            try:
                r = _run_single_edu_analyze(q, model)
                with _batch_lock:
                    state["results"].append(r)
                    state["done"] = i + 1
            except Exception as e:
                with _batch_lock:
                    state["errors"].append({"index": i, "error": str(e)})
                    state["done"] = i + 1
        with _batch_lock:
            state["status"] = "done"
            state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 自动落库到 mt_error_thinking_chain
            conn = _db()
            for r in state["results"]:
                q_data = r.get("question", {})
                thinking = json.dumps(r.get("thinking_chain", []), ensure_ascii=False)
                conn.execute("""INSERT INTO mt_error_thinking_chain
                    (user_id, subject, grade_level, question_text, user_answer, correct_answer,
                     error_type, thinking_chain, suggested_fix, ai_model)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, q_data.get('subject',''), q_data.get('grade_level',''),
                     q_data.get('question_text',''), q_data.get('user_answer',''),
                     q_data.get('correct_answer',''), r.get('error_type',''),
                     thinking, r.get('suggested_fix',''), model))
            conn.commit()
            conn.close()
    
    _threading.Thread(target=_worker, daemon=True).start()
    
    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "total": total,
        "message": f"已开始分析，进度查询 GET /api/edu/error_chain/batch/{batch_id}",
    })

@education_api.route('/api/edu/error_chain/batch/<batch_id>', methods=['GET'])
def batch_status(batch_id):
    with _batch_lock:
        state = _batch_store.get(batch_id)
    if not state:
        return jsonify({"success": False, "error": "batch 不存在"}), 404
    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "status": state["status"],
        "progress": f"{state['done']}/{state['total']}",
        "progress_pct": round(state["done"] / max(1, state["total"]) * 100, 1),
        "model": state["model"],
        "results": state["results"] if state["status"] == "done" else None,
        "errors": state["errors"],
        "started_at": state["started_at"],
        "finished_at": state["finished_at"],
    })


# ===== §二 AI 导师对话追加 =====
import threading as _tutor_th

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("EDU_OLLAMA_MODEL", "qwen2.5:7b")

_tutor_history = {}
_tutor_lock = _tutor_th.Lock()
_TUTOR_MAX_HISTORY = 20

def _ollama_chat(messages, model=None, timeout=90):
    tag = model or _OLLAMA_MODEL
    payload = {"model": tag, "messages": messages, "stream": False,
               "options": {"temperature": 0.7, "num_predict": 500}}
    try:
        req = urllib.request.Request(
            f"{_OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"[Ollama 失败: {e}]"

def _load_user_profile(user_id):
    try:
        with _db() as conn:
            row = conn.execute("SELECT * FROM mt_user_cognitive_profile WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}

def _load_error_context(user_id, limit=3):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT subject, question_text, user_answer, correct_answer, error_type "
                "FROM mt_error_thinking_chain WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []

@education_api.route("/api/edu/tutor/chat", methods=["POST"])
def tutor_chat():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id", "anonymous")
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id")
    tutor_type = data.get("tutor_type", "general")
    if not message:
        return jsonify({"success": False, "error": "message 不能为空"}), 400

    conn = _db(); cur = conn.cursor()
    tutor_map = {"general": "AI 全科导师", "math": "AI 数学导师", "physics": "AI 物理导师",
                 "chemistry": "AI 化学导师", "research": "AI 科研导师"}
    tutor_name = tutor_map.get(tutor_type, "AI 导师")

    if session_id:
        row = cur.execute("SELECT * FROM mt_ai_tutor_session WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "error": "session 不存在"}), 404
        session_id = row["session_id"]
    else:
        cur.execute(
            "INSERT INTO mt_ai_tutor_session (user_id, tutor_type, tutor_name, context_summary, last_active) "
            "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
            (user_id, tutor_type, tutor_name, f"{tutor_type}方向会话"))
        session_id = cur.lastrowid

    profile = _load_user_profile(user_id)
    errors = _load_error_context(user_id, limit=3)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    err_ctx = "".join(
        f"\n- [{e['subject']}] {e['question_text'][:50]} 错因:{e.get('error_type','?')}"
        for e in errors)
    sys_prompt = (
        f"你是{tutor_name}，专业耐心的AI导师。\n"
        f"用户画像: 认知={profile.get('cognitive_level','auto')}, "
        f"风格={profile.get('learning_style','auto')}, "
        f"关注={profile.get('focus_subjects','')}, "
        f"薄弱={profile.get('weak_subjects','')}\n"
        f"时间: {now_str}, 类型: {tutor_type}\n"
        f"最近错题: {err_ctx or '无'}\n"
        "原则: 启发引导不直接给答案, 用类比, 针对薄弱点, 简明<=300字")

    with _tutor_lock:
        hist = _tutor_history.get(session_id, [])
    messages = [{"role": "system", "content": sys_prompt}] + hist + [{"role": "user", "content": message}]
    reply = _ollama_chat(messages, timeout=90)

    with _tutor_lock:
        hist = _tutor_history.get(session_id, [])
        hist += [{"role": "user", "content": message, "ts": now_str},
                 {"role": "assistant", "content": reply, "ts": now_str}]
        if len(hist) > _TUTOR_MAX_HISTORY:
            hist = hist[-_TUTOR_MAX_HISTORY:]
        _tutor_history[session_id] = hist

    cur.execute(
        "UPDATE mt_ai_tutor_session SET message_count=message_count+1, "
        "last_active=datetime('now','localtime'), context_summary=? WHERE session_id=?",
        (message[:200], session_id))
    conn.commit(); conn.close()

    return jsonify({
        "success": True, "session_id": session_id, "tutor_name": tutor_name,
        "message": reply, "history_count": len(hist) // 2,
        "error_context_count": len(errors),
        "user_profile": {k: profile.get(k) for k in ("cognitive_level","learning_style","focus_subjects","weak_subjects")},
    })

@education_api.route("/api/edu/tutor/sessions/<user_id>", methods=["GET"])
def tutor_user_sessions(user_id):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT session_id, tutor_type, tutor_name, message_count, last_active, status "
                "FROM mt_ai_tutor_session WHERE user_id=? ORDER BY last_active DESC LIMIT 20",
                (user_id,)).fetchall()
            return jsonify({"success": True, "sessions": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@education_api.route("/api/edu/tutor/profile/<user_id>", methods=["GET"])
def tutor_profile(user_id):
    try:
        with _db() as conn:
            row = conn.execute("SELECT * FROM mt_user_cognitive_profile WHERE user_id=?", (user_id,)).fetchone()
            return jsonify({"success": True, "profile": dict(row) if row else None})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@education_api.route("/api/edu/tutor/profile/<user_id>", methods=["POST"])
def tutor_profile_update(user_id):
    data = request.get_json(silent=True) or {}
    fields = ["cognitive_level", "learning_style", "focus_subjects",
              "weak_subjects", "pace_setting", "preferred_output", "ai_tutor_type"]
    vals = {k: data[k] for k in fields if k in data}
    if not vals:
        return jsonify({"success": False, "error": "无有效字段"}), 400
    try:
        with _db() as conn:
            set_c = ", ".join(f"{k}=?" for k in vals) + ", updated_at=datetime('now','localtime')"
            conn.execute(
                f"INSERT INTO mt_user_cognitive_profile (user_id, {set_c}, created_at) "
                f"VALUES (?, {', '.join(['?']*len(vals))}, datetime('now','localtime')) "
                f"ON CONFLICT(user_id) DO UPDATE SET {set_c}",
                (user_id, *vals.values(), *vals.values()))
            conn.commit()
        return jsonify({"success": True, "updated": list(vals.keys())})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@education_api.route("/api/edu/error_chain/feed/<user_id>", methods=["GET"])
def error_feed(user_id):
    try:
        with _db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM mt_error_thinking_chain WHERE user_id=?", (user_id,)).fetchone()[0]
            subj = conn.execute(
                "SELECT subject, COUNT(*) cnt FROM mt_error_thinking_chain "
                "WHERE user_id=? GROUP BY subject ORDER BY cnt DESC",
                (user_id,)).fetchall()
        return jsonify({"success": True, "total": total,
                        "by_subject": [dict(s) for s in subj]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ===== §一 拉马努金动态衍生 =====
import importlib.util as _ilu
# education_api.py 位置: flask-app/app/api/ → dirname×3 = flask-app/ 项目根
_ram_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "ai_engines", "ramanujan_engine.py")
ramanujan = None
try:
    _ram_spec = _ilu.spec_from_file_location("ramanujan_engine", _ram_path)
    if _ram_spec:
        ramanujan = _ilu.module_from_spec(_ram_spec)
        _ram_spec.loader.exec_module(ramanujan)
except Exception as _e:
    print(f"[education_api] ramanujan_engine 加载跳过: {_e}")
    ramanujan = None

@education_api.route("/api/ai/derive", methods=["POST"])
def ramanujan_derive():
    if ramanujan is None:
        return jsonify({"success": False, "error": "ramanujan_engine 未加载"}), 500
    data = request.get_json(silent=True) or {}
    concept = (data.get("concept") or "").strip()
    if not concept:
        return jsonify({"success": False, "error": "concept 不能为空"}), 400
    subject = data.get("subject", "mathematics")
    user_id = data.get("user_id", "system")
    model = data.get("model")
    result = ramanujan.derive(concept=concept, subject=subject, user_id=user_id, model=model)
    if result.get("success"):
        return jsonify(result)
    return jsonify(result), 500

@education_api.route("/api/ai/derive/list", methods=["GET"])
def ramanujan_list():
    if ramanujan is None:
        return jsonify({"success": False, "error": "ramanujan_engine 未加载"}), 500
    subject = request.args.get("subject")
    limit = int(request.args.get("limit", 20))
    items = ramanujan.list_knowledge(subject=subject, limit=limit)
    return jsonify({"success": True, "total": len(items), "items": items})

@education_api.route("/api/ai/derive/<int:kid>", methods=["GET"])
def ramanujan_get(kid):
    if ramanujan is None:
        return jsonify({"success": False, "error": "ramanujan_engine 未加载"}), 500
    item = ramanujan.get_knowledge(kid)
    if not item:
        return jsonify({"success": False, "error": "不存在"}), 404
    return jsonify({"success": True, "item": item})

@education_api.route("/api/ai/derive/batch", methods=["POST"])
def ramanujan_batch():
    if ramanujan is None:
        return jsonify({"success": False, "error": "ramanujan_engine 未加载"}), 500
    data = request.get_json(silent=True) or {}
    concepts = data.get("concepts", [])
    if not concepts:
        return jsonify({"success": False, "error": "concepts 不能为空"}), 400
    user_id = data.get("user_id", "system")
    model = data.get("model")
    result = ramanujan.batch_derive(concepts=concepts, user_id=user_id, model=model)
    return jsonify({"success": True, "batch_result": result})

print("[EDU-API] ✅ +拉马努金衍生路由: +4 (/derive, /derive/list, /derive/<id>, /derive/batch)")

print("[EDU-API] Blueprint education_api 注册完成: 16 路由 (含 batch)")
