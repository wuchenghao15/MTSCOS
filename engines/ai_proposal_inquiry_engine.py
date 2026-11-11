"""🔍 提案深度信息咨询引擎 (flow_proposal_inquiry_20261027)

提案进入大厅 QUEUED 后, 派单之前, 自动跑 16 维度深度分析 —
每个维度生成 question_text (用户可回答) + auto_analysis_text (AI 自动分析) + suggested_answer (建议答案)。

设计:
  - 零 token: 文本由规则模板 + 历史提案库 + 中心画像自动生成, 不调 LLM
  - 落库: mt_proposal_inquiry 新表
  - 挂点: run_hall_auto() 里 QUEUED 任务先跑 generate_inquiry, AI_ANALYZED 后才进派单
  - 用户确认: SA 可批量 BYPASS, 普通用户需 USER_CONFIRMED 才能派单

16 维度:
  1. tags                自动标签化 (基于关键词)
  2. ultimate_need       最终需求是什么? (用户真正想解决什么)
  3. ultimate_purpose    最终能达到什么样的目的? (产出/效果/收益)
  4. center_involve      需要哪些中心综合介入? (16 中心匹配建议)
  5. avoid_recurrence    未来如何避免再次被提及此类似的提案? (根治方案)
  6. ai_employee_need    是否需要更多的 AI 员工介入? (角色数量+画像)
  7. similar_solutions   是否有类似的解决方案可以查阅和借阅? (历史提案库)
  8. true_intent         提案想辨明的最终意图有没有完全表达到? (真正想表达啥事)
  9. side_proposals      基于提案联想的连带提案可以一并处理的? (关联方向)
  10. direction_check    联想方向是否有偏离? (战略对齐检查)
  11. completion_baseline 完成以后的基准和标准是什么? (验收标准)
  12. ai_retention       完成以后新建的 AI 是保留还是销毁? (AI 生命周期)
  13. skill_hook_agent   是否要介入研究对应 skill/hook/agent/自动计划表? (能力封装)
  14. proactive_ideas    我是不是可以联想到用户没有想到的, 或更多? (主动联想)
  15. stakeholder_voice  用户/学生/运营等利益相关方视角? (多角度)
  16. risk_assessment    风险评估 + 回滚方案? (防崩溃兜底)
"""
import os, sys, json, sqlite3, re, uuid
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path: sys.path.insert(0, _APP_DIR)
DB_PATH = os.path.join(_APP_DIR, "Database", "app.db")
FLOW = "flow_proposal_inquiry_20261027"


# ═══════════════════════════════════════════════════════════
# 16 维度分析框架 (模板 + 历史库 + 中心画像)
# ═══════════════════════════════════════════════════════════

DIMENSIONS = [
    ("tags", "自动标签化", "系统自动为提案打上哪些标签?"),
    ("ultimate_need", "最终需求", "用户提出这个提案的最终需求是什么? 真正想解决什么核心问题?"),
    ("ultimate_purpose", "最终目的", "提案最终能达到什么样的目的? 产出什么效果? 带来什么收益?"),
    ("center_involve", "中心介入", "需要哪些中心综合介入? 每个中心做什么?"),
    ("avoid_recurrence", "避免重复", "未来如何避免再次被提及此类似的提案? 根治方案是什么?"),
    ("ai_employee_need", "AI 员工需求", "是否需要更多的 AI 员工等介入? 需要什么角色? 几个?"),
    ("similar_solutions", "相似方案", "是否有类似的解决方案可以查阅和借阅?"),
    ("true_intent", "真正意图", "提案想辨明的最终意图有没有完全表达到? 那真正想表达啥事什么?"),
    ("side_proposals", "连带提案", "基于提案联想, 有什么其他连带的提案可以一并处理的?"),
    ("direction_check", "方向检查", "联想方向是否有偏离? 是否对齐战略路线图?"),
    ("completion_baseline", "完成基准", "完成以后的基准和标准又是什么? 验收标准?"),
    ("ai_retention", "AI 保留销毁", "完成以后新建的 AI 是保留还是销毁? 生命周期如何?"),
    ("skill_hook_agent", "Skill/Hook/Agent", "是否要介入研究对应 skill, hook, agent, 自动计划表?"),
    ("proactive_ideas", "主动联想", "我是不是可以联想到用户没有想到的, 或更多?"),
    ("stakeholder_voice", "利益相关方", "用户/学生/运营/专家/监察等利益相关方视角?"),
    ("risk_assessment", "风险回滚", "风险评估 + 回滚方案? 最危险的 3 点是什么?"),
]


# ── 中心画像 (复用 ai_center_consultation_engine) ──
sys.path.insert(0, _APP_DIR)
try:
    from engines.ai_center_consultation_engine import CENTER_PROFILES
except ImportError:
    CENTER_PROFILES = {}


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════
# DDL
# ═══════════════════════════════════════════════════════════

INQUIRY_DDL = """CREATE TABLE IF NOT EXISTS mt_proposal_inquiry (
    inquiry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_task_id INTEGER NOT NULL,
    dimension_key TEXT NOT NULL,
    dimension_label TEXT NOT NULL,
    question_text TEXT NOT NULL,
    auto_analysis_text TEXT,
    suggested_answer TEXT,
    user_answer TEXT,
    status TEXT DEFAULT 'AI_ANALYZED',    -- AI_ANALYZED / USER_CONFIRMED / BYPASSED
    created_at TEXT DEFAULT (datetime('now','localtime')),
    flow_id TEXT DEFAULT 'flow_proposal_inquiry_20261027',
    UNIQUE(hall_task_id, dimension_key)
)"""


def ensure_tables():
    c = get_conn()
    c.execute(INQUIRY_DDL)
    c.commit()
    c.close()


# ═══════════════════════════════════════════════════════════
# 核心分析函数
# ═══════════════════════════════════════════════════════════

_KW_CATEGORIES = [
    ("教育", re.compile(r"(教育|题库|考试|教学|备课|试题|学情|组卷|批改|讲解|考点|学生|数学|物理|语文|化学)", re.I)),
    ("AI", re.compile(r"(ollama|向量|embedding|推理|eigenflux|脑库|llm|模型|ai|引擎|专家|雇佣|群智|神经网络)", re.I)),
    ("开发", re.compile(r"(dev|git|flask|commit|代码|merge|review|ci|开发|流程|flow|branch|blueprint)", re.I)),
    ("安全", re.compile(r"(漏洞|注入|加密|风险|红线|审计|安全|白帽|猎捕|shell|硬编码|凭证)", re.I)),
    ("运维", re.compile(r"(daemon|挂载|keepalive|巡检|修复|部署|ops|云|docker|容器|进程|端口)", re.I)),
    ("前端", re.compile(r"(前端|ui|页面|交互|设计token|渲染|组件|html|css|js|冰山|响应式|移动端)", re.I)),
    ("数据", re.compile(r"(数据|分析|报告|统计|画像|etl|报表|学情|正确率|趋势|指标|kpi)", re.I)),
    ("规则", re.compile(r"(规则|rule|变更|changelog|铁律|治理|违反|立法|法条|法案|法令|委员会|常委会)", re.I)),
    ("人力", re.compile(r"(人力|人事|员工|雇佣|绩效|培训|认证|roster|注册|名册|考勤|薪酬)", re.I)),
    ("专家", re.compile(r"(专家|eigenflux|磋商|表决|连线|心跳|群智|多专家|团队|hire|form_team)", re.I)),
    ("工作流", re.compile(r"(工作流|workflow|流水线|调度|编排|任务链|协作|daemon|tick|状态机)", re.I)),
    ("战略", re.compile(r"(战略|strategy|策略|规划|plan|决策|decision|进化|evolution|方向|愿景|路线图)", re.I)),
    ("Skill", re.compile(r"(skill|技能|衍生|SKILL.md|能力库|skill-creator|封装|模板|可复用|pipeline)", re.I)),
    ("监察", re.compile(r"(监察|督办|跟进|研究|完善|备案|回档|巡检|审计|复盘|合规|violation)", re.I)),
    ("法务", re.compile(r"(法务|合规|legal|风险|个保法|网安法|消保法|数据|隐私|脱敏)", re.I)),
]


def _auto_tag(text: str) -> list:
    tags = []
    for label, pat in _KW_CATEGORIES:
        if pat.search(text):
            tags.append(label)
    return list(dict.fromkeys(tags))  # 去重保序


def _match_centers(text: str) -> list:
    """匹配 16 个中心中相关的"""
    matched = []
    for cid, prof in CENTER_PROFILES.items():
        score = 0
        hits = prof["kw"].findall(text)
        score = min(1.0, len(set(h.lower() for h in hits)) / 6.0)
        if score > 0.05:
            matched.append((cid, prof["name"], prof["code"], round(score, 3), prof["req"]))
    matched.sort(key=lambda x: -x[3])
    return matched


def _find_similar_solutions(conn, text: str, limit=3) -> list:
    """从历史提案库找相似解决方案"""
    tags = set(_auto_tag(text))
    rows = conn.execute(
        "SELECT id, hall_code, title, description, source FROM mt_lab_task_hall "
        "WHERE status IN ('DISPATCHED','DONE','COMPLETED','IN_PROGRESS') "
        "ORDER BY id DESC LIMIT 50").fetchall()
    results = []
    for r in rows:
        rt = _auto_tag(f"{r['title']} {r['description'] or ''}")
        overlap = tags & set(rt)
        if overlap and len(overlap) >= max(1, len(tags) // 2):
            results.append({"hall_code": r['hall_code'], "title": r['title'],
                            "overlap_tags": list(overlap), "source": r['source']})
        if len(results) >= limit: break
    return results


def _generate_dimension(conn, task, dim_key: str, dim_label: str, question: str) -> dict:
    """生成单个维度的 auto_analysis + suggested_answer"""
    text = f"{task['title']} {task['description'] or ''}"
    tags = _auto_tag(text)
    centers = _match_centers(text)

    auto = ""
    sug = ""

    if dim_key == "tags":
        auto = f"基于关键词自动识别标签: {', '.join(tags) if tags else '无明显标签 (通用提案)'}"
        sug = f"建议标签: {', '.join(tags) if tags else '补充提案描述以触发标签识别'}"

    elif dim_key == "ultimate_need":
        auto = (f"从关键词 [{', '.join(tags) if tags else '通用'}] 和描述推断, "
                f"用户的核心需求是: {task['title'][:60]}。"
                f"关键词密度: tags={len(tags)}, 描述长度={len(text)}。"
                f"可能的深层需求: 该领域现有能力不足, 需要系统性补强。")
        sug = "请用户确认: 真正想解决的核心问题是什么? 是不是比描述里写的更深层?"

    elif dim_key == "ultimate_purpose":
        matched_names = [c[1] for c in centers[:5]]
        auto = (f"预期产出: 该提案上线后, {', '.join(matched_names[:3]) if matched_names else '相关中心'} "
                f"的能力将补齐, 系统整体覆盖率提升。"
                f"具体收益取决于中心介入度和执行质量。")
        sug = "请用户明确: 这个提案最终要达到什么具体目的? 可以量化的产出/效果/收益是什么?"

    elif dim_key == "center_involve":
        if centers:
            c_text = "\n".join(f"  ({cid}) {name} [{code}] score={sc}: {req[:50]}..."
                              for cid, name, code, sc, req in centers[:8])
            auto = f"基于关键词匹配, 以下中心应介入:\n{c_text}"
        else:
            auto = "无高匹配中心, 建议全量 16 中心介入 (通用提案, 每个中心从自己视角给出关切)"
        sug = "请用户确认: 这些中心是否都需要介入? 有没有遗漏? 有没有不想让某些中心介入的?"

    elif dim_key == "avoid_recurrence":
        auto = (f"根治方向: 把这个提案要求的能力写入立法委法条 + 封装为 Skill + daemon tick 自动检查。"
                f"具体: 在 mt_proposal_inquiry 里自动识别同类提案并标记, "
                f"daemon 每 15min tick 扫描 mt_lab_task_hall 是否有重复关键词提案。")
        sug = "请用户确认: 根治方案是否覆盖了所有可能的复发场景? 是否需要额外的预防机制?"

    elif dim_key == "ai_employee_need":
        domain = tags[0] if tags else "通用"
        auto = (f"基于 [{domain}] 领域关键词密度, 建议: "
                f"EigenFlux hire_batch(domain='{domain}', count=4) → "
                f"其中 chief×1 + expert×2 + senior×1, 然后 form_team + hr_registry 注册。"
                f"如果已有足够专家 (mt_hr_center_registry 覆盖), 则只需 form_team 现有专家。")
        sug = "请用户确认: 需要新雇佣 AI 员工还是复用现有? 几个? 什么角色画像?"

    elif dim_key == "similar_solutions":
        sims = _find_similar_solutions(conn, text, limit=3)
        if sims:
            auto = "历史相似提案:\n" + "\n".join(
                f"  - {s['hall_code']} [{s['source']}] {s['title'][:40]} (重叠标签: {', '.join(s['overlap_tags'])})"
                for s in sims)
        else:
            auto = "未找到高重叠历史提案 — 这可能是一个新领域, 建议创新路径。"
        sug = "请用户确认: 这些历史提案是否真的相似? 是否可以直接复用? 还是需要全新方案?"

    elif dim_key == "true_intent":
        title_keywords = [w for w in re.split(r"[^\w\u4e00-\u9fff]+", task['title']) if len(w) > 1][:6]
        desc_keywords = [w for w in re.split(r"[^\w\u4e00-\u9fff]+", task['description'] or "") if len(w) > 1][:6]
        auto = (f"标题关键词: {', '.join(title_keywords)}\n"
                f"描述关键词: {', '.join(desc_keywords)}\n"
                f"标题 vs 描述重叠度: {len(set(title_keywords) & set(desc_keywords)) / max(len(title_keywords),len(desc_keywords),1):.0%}\n"
                f"如果重叠度低, 说明提案可能表述不足或标题/描述不一致, 真实意图可能没完全表达。")
        sug = "请用户回答: 这个提案真正想表达啥事? 有没有没说出来的深层诉求?"

    elif dim_key == "side_proposals":
        auto = (f"基于 [{', '.join(tags[:3]) if tags else '通用'}] 领域联想, 可能的连带提案:\n"
                f"  ① 相关领域 Skill 封装 (skill-creator 自动触发)\n"
                f"  ② 跨学科/跨领域能力对齐\n"
                f"  ③ 存量同类提案统一回档 (mt_proposal_implementation_log)\n"
                f"  ④ 数据库/表结构升级 (如果涉及新能力)\n"
                f"  ⑤ 前端 UI 配套")
        sug = "请用户确认: 这些连带提案是不是应该一并处理? 有没有其他想到的?"

    elif dim_key == "direction_check":
        auto = (f"战略对齐检查: 提案涉及 [{', '.join(tags[:3]) if tags else '通用'}], "
                f"对照战略中心 (id=1421) keywords (战略/策略/规划/决策/进化), "
                f"{'高度对齐 ✅' if any(k in tags for k in ['战略','Skill','工作流']) else '中度对齐 ⚠️ 建议战略中心评审'}。"
                f"方向偏离风险: 如果偏离, 建议 SA 特批 + 战略中心打分 (1-10)。")
        sug = "请用户确认: 方向是不是有偏离? 是否需要战略中心评审?"

    elif dim_key == "completion_baseline":
        auto = (f"完成基准 (建议 5 条):\n"
                f"  ① 核心功能上线可用 (CLI demo 跑通)\n"
                f"  ② 所有中心 mt_center_proposal_consultations 覆盖 ≥ 14/16\n"
                f"  ③ 立法委法条走完 (mt_committee_decrees status=ENACTED)\n"
                f"  ④ HR mt_hr_center_registry 注册齐全 + mt_hr_training_log 培训通过\n"
                f"  ⑤ 零 CRITICAL/HIGH 漏洞 (白帽猎捕 SAST 扫描)")
        sug = "请用户确认: 这个验收标准对不对? 要不要加/减/改?"

    elif dim_key == "ai_retention":
        auto = (f"AI 生命周期: EigenFlux 专家是保留 (hire_batch 永久雇佣), "
                f"临时训练的 AI 可以销毁。"
                f"保留理由: 该领域需要持续迭代 (如数学题型库扩充), 专家 heartbeat 维持活性。"
                f"销毁条件: 如果是一次性任务且后续无需求, 走 mt_hr_center_registry revoke。")
        sug = "请用户确认: 新建 AI 保留还是销毁? 生命周期预期?"

    elif dim_key == "skill_hook_agent":
        domain = tags[0] if tags else "通用"
        auto = (f"Skill: flow_skill_derivation_20261027 自动触发 → 封装为可复用 Skill (SKILL.md + frontmatter)\n"
                f"Hook: 在 _hall_dispatch_one → AI_ANALYZED 后自动调 generate_inquiry\n"
                f"Agent: 如果需要 LLM 精修, 可挂 ai_local_chat_bp + 本地 ollama\n"
                f"自动计划表: daemon 15min tick 推进 (QUEUED → AI_ANALYZED → USER_CONFIRMED → DISPATCHED)")
        sug = "请用户确认: 要不要介入 Skill/Hook/Agent/自动计划表? 哪个优先?"

    elif dim_key == "proactive_ideas":
        auto = (f"主动联想 (系统自动生成, 用户可能没想到的):\n"
                f"  ① 提案本身可能触发新 Skill 封装 (skill_derivation 自动触发)\n"
                f"  ② 可以同时做一个 [提案深度咨询] 自己的 Skill 模板\n"
                f"  ③ 把 16 维度分析做成可配置, SA 可以定制维度\n"
                f"  ④ 历史提案相似度匹配可以扩展为提案推荐引擎\n"
                f"  ⑤ 可以和 mt_andromeda_rule_knowledge 联动, 自动投喂脑库")
        sug = "请用户补充: 有没有系统没想到的? 更多想法?"

    elif dim_key == "stakeholder_voice":
        auto = (f"利益相关方视角:\n"
                f"  👨‍🎓 用户/学生: 这个提案能帮我解决什么? 会不会给我增加负担?\n"
                f"  🏢 运营: 这个提案上线后怎么推广? 用户会不会用?\n"
                f"  👨‍💻 专家: 这个提案的技术方向对不对? 有没有更好的做法?\n"
                f"  🔍 监察: 有没有违反铁律? 需不需要巡检?\n"
                f"  ⚖️ 法务: 数据合规吗? 有没有法律风险?")
        sug = "请用户代入不同利益相关方: 他们会不会有不同想法?"

    elif dim_key == "risk_assessment":
        auto = (f"风险 Top 3:\n"
                f"  🔴 最高风险: 只走了部分轨 (六轨缺一) → 合规漏洞 → 用户追问'为什么 XX 没介入'\n"
                f"  🟡 中等风险: 关键词匹配偏差 → 中心介入不对 → 方向偏离 → SA 特批\n"
                f"  🟢 低风险: EigenFlux 专家 heartbeat 超时 → 专家离线 → 重新 hire_batch\n"
                f"回滚方案: 走 mt_committee_decrees revoked_by_bill + mt_hr_center_registry revoke + daemon tick 自动回退")
        sug = "请用户确认: 风险评估对不对? 回滚方案够不够?"

    return {
        "dimension_key": dim_key,
        "dimension_label": dim_label,
        "question_text": question,
        "auto_analysis_text": auto,
        "suggested_answer": sug,
    }


# ═══════════════════════════════════════════════════════════
# 主入口: 为单个提案生成 16 维度咨询
# ═══════════════════════════════════════════════════════════

def generate_inquiry(hall_task_id: int) -> int:
    """生成 16 维度, 返回写入条数"""
    conn = get_conn()
    task = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (hall_task_id,)).fetchone()
    if not task:
        conn.close()
        return 0

    hall_code = task['hall_code']
    written = 0
    for dim_key, dim_label, question in DIMENSIONS:
        existing = conn.execute(
            "SELECT inquiry_id FROM mt_proposal_inquiry WHERE hall_task_id=? AND dimension_key=?",
            (hall_task_id, dim_key)).fetchone()
        if existing:
            continue  # 已存在跳过, 防重复
        d = _generate_dimension(conn, task, dim_key, dim_label, question)
        conn.execute("""INSERT INTO mt_proposal_inquiry
(hall_task_id, dimension_key, dimension_label, question_text, auto_analysis_text, suggested_answer)
VALUES (?,?,?,?,?,?)""",
                     (hall_task_id, d["dimension_key"], d["dimension_label"],
                      d["question_text"], d["auto_analysis_text"], d["suggested_answer"]))
        written += 1

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(f"[INQUIRY] 🔍 {hall_code} → {written} 条深度咨询 (16 维度)")
    return written


def generate_all_active():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, hall_code, title FROM mt_lab_task_hall "
        "WHERE status IN ('QUEUED','DISPATCHED','IN_PROGRESS')").fetchall()
    conn.close()
    total = 0
    for r in rows:
        try:
            n = generate_inquiry(r['id'])
            total += n
        except Exception as e:
            print(f"[INQUIRY] ⚠️ {r['hall_code']} 失败: {e}")
    print(f"\n[INQUIRY] 全量完成: {total} 条")


def confirm(hall_task_id: int, dimension_key: str, answer: str):
    conn = get_conn()
    conn.execute("""UPDATE mt_proposal_inquiry SET user_answer=?, status='USER_CONFIRMED'
WHERE hall_task_id=? AND dimension_key=?""",
                  (answer, hall_task_id, dimension_key))
    conn.commit()
    conn.close()


def bypass_all(hall_task_id: int):
    """SA 批量 BYPASS 所有维度"""
    conn = get_conn()
    conn.execute("UPDATE mt_proposal_inquiry SET status='BYPASSED' WHERE hall_task_id=?",
                 (hall_task_id,))
    conn.commit()
    conn.close()


def all_confirmed_or_bypassed(hall_task_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("""SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN status IN ('USER_CONFIRMED','BYPASSED') THEN 1 ELSE 0 END) AS done
FROM mt_proposal_inquiry WHERE hall_task_id=?""", (hall_task_id,)).fetchone()
    conn.close()
    return row['total'] > 0 and row['done'] == row['total']


def status(hall_task_id: int):
    conn = get_conn()
    rows = conn.execute("""SELECT dimension_key, dimension_label, question_text,
                                  substr(auto_analysis_text,1,120) AS auto_analysis,
                                  substr(suggested_answer,1,80) AS suggested,
                                  user_answer, status
FROM mt_proposal_inquiry WHERE hall_task_id=? ORDER BY inquiry_id""",
                         (hall_task_id,)).fetchall()
    task = conn.execute("SELECT hall_code, title FROM mt_lab_task_hall WHERE id=?",
                         (hall_task_id,)).fetchone()
    conn.close()
    if not task:
        print(f"任务 {hall_task_id} 不存在")
        return
    confirmed = sum(1 for r in rows if r['status'] in ('USER_CONFIRMED', 'BYPASSED'))
    print(f"\n=== {task['hall_code']} {task['title']} ===")
    print(f"   进度: {confirmed}/{len(rows)} 已确认/BYPASS")
    for i, r in enumerate(rows, 1):
        icon = "✅" if r['status'] == 'USER_CONFIRMED' else ("⏭️" if r['status'] == 'BYPASSED' else "🤖")
        print(f"\n  {i:>2}. [{r['dimension_label']}] {icon} {r['status']}")
        print(f"      问: {r['question_text']}")
        print(f"      AI: {r['auto_analysis']}")
        if r['suggested']:
            print(f"      建: {r['suggested']}")
        if r['user_answer']:
            print(f"      答: {r['user_answer']}")


if __name__ == "__main__":
    ensure_tables()
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", type=int, help="hall_task_id")
    ap.add_argument("--all", action="store_true", help="全量补生成")
    ap.add_argument("--status", type=int, help="查看结果")
    ap.add_argument("--demo", action="store_true", help="对数学任务演示")
    ap.add_argument("--bypass", type=int, help="SA 批量 BYPASS")
    args = ap.parse_args()

    if args.once:
        generate_inquiry(args.once)
    elif args.all:
        generate_all_active()
    elif args.status:
        status(args.status)
    elif args.bypass:
        bypass_all(args.bypass)
        print(f"[INQUIRY] SA BYPASS 全部维度 task={args.bypass}")
    elif args.demo:
        conn = get_conn()
        r = conn.execute("SELECT id FROM mt_lab_task_hall WHERE hall_code='TH-20261027-0011'").fetchone()
        conn.close()
        if r:
            generate_inquiry(r['id'])
            status(r['id'])
        else:
            print("TH-20261027-0011 不存在")
